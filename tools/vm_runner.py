#!/usr/bin/env python3
"""One separately authorized AOSP35 fixture VM, with owned-process teardown.

Uses existing sudo only to supervise the official emulator when KVM requires it.
Never changes host KVM permissions, guest security policy, or Root-manager state.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

import vm_validate as vm

AVD_NAME = 'guizang_fixture_gate'
IMAGE = 'system-images;android-35;google_apis;x86_64'
SERIAL = 'emulator-5554'


def verify_avd_identity(adb):
    # Official Android emulator tools use this boot property when console AVD
    # lookup is empty. A conflicting response is never treated as unavailable.
    console = adb.command('emu', 'avd', 'name')
    lines = console.splitlines()
    if lines and lines not in ([AVD_NAME], [AVD_NAME, 'OK']):
        raise vm.ExperimentFailure('Unexpected or conflicting AVD console identity')
    property_name = adb.shell('getprop', 'ro.boot.qemu.avd_name')
    if property_name != AVD_NAME:
        raise vm.ExperimentFailure('Connected emulator boot property is not this owned AVD')
    return {'console_response': console, 'boot_property': property_name,
            'console_available': bool(lines)}


def enable_debug_root(adb):
    # Some official userdebug adbd versions close the request while restarting.
    # Never interpret an authorization/permission error as a transient closure.
    try:
        response = adb.command('root', timeout=30)
    except vm.AdbFailure as error:
        if not re.fullmatch(r'(?:adb: )?error: closed', error.detail, re.I):
            raise
        response = 'adbd closed the root request; verified after reconnect'
    adb.command('wait-for-device', timeout=45)
    adb.validate_vm()
    return response


def kvm_state():
    info = os.stat('/dev/kvm')
    if not stat.S_ISCHR(info.st_mode):
        raise vm.ExperimentFailure('/dev/kvm is not a character device')
    result = {'uid': info.st_uid, 'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode),
              'rdev': info.st_rdev, 'inode': info.st_ino}
    if shutil.which('getfacl'):
        result['acl'] = subprocess.run(['getfacl', '-cp', '/dev/kvm'], check=True,
                                       capture_output=True, text=True, timeout=10).stdout
    return result


def remove_owned_home(home, token):
    home = Path(home)
    if (home.is_symlink() or home != home.resolve() or not home.name.startswith('guizang-avd-')
            or home.parent == Path('/')):
        raise vm.ExperimentFailure('Refusing cleanup outside the owned temporary AVD home')
    marker = home / '.guizang-owner.json'
    if marker.is_symlink() or json.loads(marker.read_text()) != {'owner': 'guizang-vm-runner', 'token': token}:
        raise vm.ExperimentFailure('Temporary AVD ownership marker mismatch')
    shutil.rmtree(home)
    if home.exists():
        raise vm.ExperimentFailure('Temporary AVD home survived cleanup')


def terminate_and_reap(child):
    if child.poll() is None:
        child.terminate()
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=10)
    return child.returncode


def supervise_emulator(binary, cleanup_report, home, token):
    child = None
    result = {'started_at': vm.timestamp(), 'emulator_started': False,
              'emulator_reaped': False, 'owned_home_removed': False}
    def stop(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        command = [str(binary), '-avd', AVD_NAME, '-port', '5554', '-no-window',
                   '-gpu', 'swiftshader_indirect', '-no-snapshot', '-noaudio',
                   '-no-boot-anim', '-camera-back', 'none', '-accel', 'on']
        child = subprocess.Popen(command)
        result.update(emulator_started=True, pid=child.pid)
        return child.wait()
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if child is not None:
                result['returncode'] = terminate_and_reap(child)
                result['emulator_reaped'] = True
            # The root-owned emulator files are only in our fresh, marked home.
            # Preserve creation/config evidence outside this home before launch.
            remove_owned_home(home, token)
            result['owned_home_removed'] = True
        except Exception as error:
            result['cleanup_error'] = str(error)
        finally:
            result['finished_at'] = vm.timestamp()
            vm.save_json(cleanup_report, result)


def find_sdk_tool(sdk, folder, tool):
    candidates = list((sdk / folder).glob('*/' + tool))
    if folder == 'cmdline-tools':
        candidates = list((sdk / folder).glob('*/bin/' + tool))
        preferred = sdk / folder / 'latest/bin' / tool
        if preferred.is_file():
            return preferred
    candidates = [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]
    if not candidates:
        raise vm.ExperimentFailure('Installed official SDK tool missing: ' + tool)
    # Build-tools versions consist of numeric components; avoid lexical 9 > 35.
    return max(candidates, key=lambda p: tuple(int(n) for n in re.findall(r'\d+', str(p.parent))))


def verify_cleanup(result, before, after, home):
    if before != after:
        raise vm.ExperimentFailure('KVM device metadata changed')
    if (result.get('emulator_started') is not True or result.get('emulator_reaped') is not True
            or result.get('owned_home_removed') is not True or Path(home).exists()):
        raise vm.ExperimentFailure('Emulator exit/reaping/owned-AVD deletion evidence missing')


def run(args):
    if not args.ack_disposable_vm:
        raise vm.ExperimentFailure('Separate approval and --ack-disposable-vm are required')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'started_at': vm.timestamp(), 'result': 'FAIL', 'image': IMAGE,
              'avd': AVD_NAME, 'serial': SERIAL, 'source_commit': os.environ.get('GITHUB_SHA'),
              'scope': vm.PACKAGE, 'root_scope': 'debug adb root in this disposable VM only'}
    launcher = None
    home = None
    token = secrets.token_hex(24)
    cleanup_path = output / 'emulator-cleanup.json'
    env = os.environ.copy()
    old_env = os.environ.copy()
    adb = None
    def stop(signum, frame):
        raise SystemExit(128 + signum)
    previous_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        sdk = Path(os.environ.get('ANDROID_HOME') or os.environ['ANDROID_SDK_ROOT']).resolve()
        binary, adb_path = sdk / 'emulator/emulator', sdk / 'platform-tools/adb'
        for path in (binary, adb_path):
            if not path.is_file():
                raise vm.ExperimentFailure('Official SDK binary missing: ' + str(path))
        source = sdk / 'system-images/android-35/google_apis/x86_64/source.properties'
        properties = source.read_text()
        if 'AndroidVersion.ApiLevel=35' not in properties.replace(' ', '') or 'SystemImage.Abi=x86_64' not in properties.replace(' ', ''):
            raise vm.ExperimentFailure('Installed image is not Android35 x86_64')
        (output / 'image-source.properties').write_text(properties)
        report['kvm_before'] = kvm_state()
        report['runner_kvm_access'] = os.access('/dev/kvm', os.R_OK | os.W_OK)
        if not report['runner_kvm_access']:
            # Query pre-existing permission only; never chmod/chown/groups/udev.
            subprocess.run(['sudo', '-n', 'test', '-r', '/dev/kvm'], check=True, timeout=10)
            subprocess.run(['sudo', '-n', 'test', '-w', '/dev/kvm'], check=True, timeout=10)
        for port in (5554, 5555):
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', port))
        home = Path(tempfile.mkdtemp(prefix='guizang-avd-', dir=os.environ.get('RUNNER_TEMP'))).resolve()
        vm.save_json(home / '.guizang-owner.json', {'owner': 'guizang-vm-runner', 'token': token})
        avd_home = home / 'avd'
        avd_home.mkdir()
        report['initial_creation'] = {'created_at': vm.timestamp(), 'temporary_home': str(home),
                                      'empty_avd_home': list(avd_home.iterdir()) == []}
        env.update(HOME=str(home), ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk),
                   ANDROID_AVD_HOME=str(avd_home))
        os.environ.update(env)
        adb = vm.Adb(str(adb_path), SERIAL, evidence=output / 'runner-adb.jsonl')
        connected = subprocess.run([str(adb_path), 'devices'], check=True, capture_output=True,
                                   text=True, timeout=15, env=env).stdout
        (output / 'devices-before.txt').write_text(connected)
        if any(line.strip() for line in connected.splitlines()[1:]):
            raise vm.ExperimentFailure('Runner already has an ADB target; refusing a shared device session')
        manager = find_sdk_tool(sdk, 'cmdline-tools', 'avdmanager')
        # No --force, no reuse, no license auto-acceptance. Image was installed by
        # SDK manager using preaccepted runner licenses before this invocation.
        creation = subprocess.run([str(manager), 'create', 'avd', '--name', AVD_NAME,
            '--package', IMAGE, '--device', 'pixel_2'], input='no\n', text=True,
            capture_output=True, timeout=90, env=env)
        (output / 'avd-creation.txt').write_text(creation.stdout + creation.stderr)
        if creation.returncode:
            raise vm.ExperimentFailure('Fresh AVD creation failed')
        config = avd_home / (AVD_NAME + '.avd/config.ini')
        (output / 'avd-config-initial.ini').write_text(config.read_text())
        lines = [line for line in config.read_text().splitlines()
                 if not line.startswith(('hw.ramSize=', 'vm.heapSize='))]
        config.write_text('\n'.join([*lines, 'hw.ramSize=3072', 'vm.heapSize=512']) + '\n')
        (output / 'avd-config-launched.ini').write_text(config.read_text())
        report['initial_creation']['files'] = sorted(str(p.relative_to(home)) for p in home.rglob('*'))
        vm.save_json(output / 'runner-lifecycle.json', report)
        command = [sys.executable, str(Path(__file__).resolve()), '--supervisor',
                   '--binary', str(binary), '--cleanup-report', str(cleanup_path),
                   '--owned-home', str(home), '--ownership-token', token]
        if not report['runner_kvm_access']:
            command = ['sudo', '-n', 'env', *[key + '=' + env[key] for key in
                       ('HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'ANDROID_AVD_HOME')], *command]
        with (output / 'emulator.log').open('w') as log:
            launcher = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                if launcher.poll() is not None:
                    raise vm.ExperimentFailure('Emulator exited before boot; inspect emulator.log')
                try:
                    if adb.shell('getprop', 'sys.boot_completed', timeout=10) == '1':
                        break
                except vm.AdbFailure as error:
                    if any(value in error.detail.lower() for value in ('unauthorized', 'permission denied')):
                        raise
                except subprocess.TimeoutExpired:
                    pass
                time.sleep(2)
            else:
                raise vm.ExperimentFailure('Android boot timeout')
            # Confirm image identity BEFORE requesting debug Root.
            expected = {'ro.kernel.qemu': '1', 'ro.build.version.sdk': '35',
                        'ro.product.cpu.abi': 'x86_64', 'ro.debuggable': '1'}
            report['guest_properties'] = {name: adb.shell('getprop', name) for name in expected}
            if report['guest_properties'] != expected:
                raise vm.ExperimentFailure('Unexpected emulator/image/debug identity; no root requested')
            report['avd_identity'] = verify_avd_identity(adb)
            report['debug_root_response'] = enable_debug_root(adb)
            report['boot_id'] = adb.boot_id()
            aapt = find_sdk_tool(sdk, 'build-tools', 'aapt')
            base = [sys.executable, str(Path(__file__).with_name('vm_validate.py')),
                    '--serial', SERIAL, '--adb', str(adb_path), '--ack-disposable-vm',
                    '--probe', str(args.probe.resolve()), '--apk', str(args.apk.resolve()),
                    '--aapt', str(aapt), '--receipt', str(output / 'installation-receipt.json')]
            def round_run(name, extra, expected_exit=0):
                destination = output / name
                with (output / (name + '.log')).open('w') as stream:
                    child = subprocess.run([*base, '--output', str(destination), *extra],
                                           stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=180)
                report[name + '_exit'] = child.returncode
                if child.returncode != expected_exit:
                    raise vm.ExperimentFailure(name + ' exited unexpectedly: ' + str(child.returncode))
                return json.loads((destination / 'result.json').read_text())
            qualification = round_run('qualification', ['--mode', 'probe'])
            if qualification.get('passed') is not True:
                raise vm.ExperimentFailure('Read-only qualification incomplete')
            normal = round_run('normal', ['--mode', 'freeze-test'])
            if normal.get('passed') is not True:
                raise vm.ExperimentFailure('Normal freeze/thaw evidence incomplete')
            fault = round_run('coordinator-interruption', ['--mode', 'freeze-test',
                '--reuse-fixture', '--fault-coordinator-exit'], expected_exit=73)
            if not fault.get('frozen') or fault.get('boot_id') != report['boot_id']:
                raise vm.ExperimentFailure('Coordinator did not exit from the verified frozen state')
            watchdog_path = output / 'coordinator-interruption/watchdog-result.json'
            deadline = time.monotonic() + 95
            while not watchdog_path.is_file() and time.monotonic() < deadline:
                time.sleep(0.5)
            recovery = json.loads(watchdog_path.read_text())
            if recovery.get('attempted') is not True or recovery.get('verified_thaw') is not True:
                raise vm.ExperimentFailure('Independent watchdog recovery is unproven')
            before = fault['before']['heartbeat']
            fault['resumed'] = vm.observe_thaw(adb, before, fault['frozen']['heartbeat_end']['counter'])
            vm.collect_diagnostics(adb, fault)
            fault.update(passed=True, result='INTERRUPTION_RECOVERY_EVIDENCE_PASS',
                         coordinator_exit=73, watchdog=recovery, finished_at=vm.timestamp())
            vm.save_json(output / 'coordinator-interruption/recovery-verdict.json', fault)
            # No reinstall/reset between rounds; recheck exact installed APK bytes.
            if vm.installed_apk_hash(adb) != vm.sha256(args.apk):
                raise vm.ExperimentFailure('Fixture APK changed during the session')
            report['terminal_fixture'] = vm.observe_thaw(adb, before, fault['resumed']['heartbeat']['counter'])
            report['result'] = 'PASS'
            report['meaning'] = 'This image and same-build fixture only; no production/device safety claim'
    except BaseException as error:
        report.update(result='FAIL', error=str(error) or type(error).__name__)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if launcher is not None:
            try:
                if adb is not None:
                    adb.command('emu', 'kill', timeout=10)
            except (vm.ExperimentFailure, subprocess.SubprocessError, OSError):
                pass
            if launcher.poll() is None:
                launcher.terminate()  # sudo forwards TERM; supervisor reaps direct child.
            try:
                launcher.wait(timeout=45)
                report['launcher_reaped'] = True
                cleanup = json.loads(cleanup_path.read_text())
                report['kvm_after'] = kvm_state()
                verify_cleanup(cleanup, report['kvm_before'], report['kvm_after'], home)
                report['cleanup_verified'] = True
            except Exception as error:
                report.update(result='FAIL', cleanup_error=str(error), cleanup_verified=False)
        elif home is not None:
            try:
                remove_owned_home(home, token)
                report['unlaunched_home_removed'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
        if 'kvm_before' in report and 'kvm_after' not in report:
            try:
                report['kvm_after'] = kvm_state()
                if report['kvm_before'] != report['kvm_after']:
                    report.update(result='FAIL', cleanup_error='KVM metadata changed')
            except Exception as error:
                report.update(result='FAIL', cleanup_error=str(error))
        report['finished_at'] = vm.timestamp()
        vm.save_json(output / 'runner-lifecycle.json', report)
        os.environ.clear()
        os.environ.update(old_env)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return 0 if report['result'] == 'PASS' and report.get('cleanup_verified') else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ack-disposable-vm', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--probe', type=Path)
    parser.add_argument('--apk', type=Path)
    parser.add_argument('--supervisor', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--binary', help=argparse.SUPPRESS)
    parser.add_argument('--cleanup-report', help=argparse.SUPPRESS)
    parser.add_argument('--owned-home', help=argparse.SUPPRESS)
    parser.add_argument('--ownership-token', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.supervisor:
        return supervise_emulator(args.binary, args.cleanup_report, args.owned_home, args.ownership_token)
    if not all((args.output, args.probe, args.apk)):
        parser.error('--output, --probe and --apk are required')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
