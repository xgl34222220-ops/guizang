#!/usr/bin/env python3
"""Disposable-AVD fixture experiment. NEVER run without the separate user approval.

No automatic Root elevation, image patches, freezer global settings or raw cgroup writes.
The acknowledgment flag is a guardrail; it is not a substitute for authorization.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

PACKAGE = 'org.guizang.fixture'
REMOTE_PROBE = '/data/local/tmp/guizang-probe'


class ExperimentFailure(RuntimeError):
    pass


def validate_serial(serial):
    if not re.fullmatch(r'emulator-[0-9]{4,5}', serial):
        raise ExperimentFailure('Only a named local emulator serial is accepted')
    return serial


def same_instance(a, b):
    return all(a.get(k) == b.get(k) and a.get(k) is not None
               for k in ('nonce', 'pid', 'uid', 'starttime'))


def require_heartbeat(h):
    if (not isinstance(h, dict) or not isinstance(h.get('nonce'), str) or not h['nonce']
            or type(h.get('pid')) is not int or h['pid'] < 2
            or type(h.get('uid')) is not int or not 10000 <= h['uid'] < 20000
            or not isinstance(h.get('starttime'), str) or not h['starttime'].isdigit()
            or int(h['starttime']) <= 0 or type(h.get('counter')) is not int or h['counter'] < 1):
        raise ExperimentFailure('Invalid fixture heartbeat')
    return h


def ams_frozen(dump, pid):
    lines = dump.splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(r'\s*Apps frozen: (\d+)\s*', line)
        if not match:
            continue
        count = int(match[1])
        if count > 1000 or index + count >= len(lines):
            raise ExperimentFailure('Incomplete AMS frozen section')
        entries = lines[index + 1:index + 1 + count]
        pattern = r'\s*\d+: (\d+) ([a-zA-Z0-9_.:]+)(?: \(sticky\))?\s*'
        parsed = [re.fullmatch(pattern, entry) for entry in entries]
        if any(item is None for item in parsed):
            raise ExperimentFailure('Unrecognized AMS frozen entry')
        return any(int(item[1]) == pid and item[2] == PACKAGE for item in parsed)
    raise ExperimentFailure('AMS frozen section missing')


class Adb:
    def __init__(self, executable, serial, run=subprocess.run):
        self.executable, self.serial, self.run = executable, validate_serial(serial), run

    def command(self, *args, timeout=15):
        # Parameters below are library-owned literals, except validated PIDs/local input paths.
        result = self.run([self.executable, '-s', self.serial, *map(str, args)],
                          check=False, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise ExperimentFailure('ADB operation failed: ' + ' '.join(map(str, args[:3])))
        return result.stdout.strip()

    def shell(self, *args, **kwargs):
        return self.command('shell', *args, **kwargs)

    def validate_vm(self):
        if self.shell('getprop', 'ro.kernel.qemu') != '1':
            raise ExperimentFailure('Selected target is not a verified emulator')
        if self.shell('id', '-u') != '0':
            raise ExperimentFailure('Debug Root is not active; obtain approval before adb root')
        if self.shell('am', 'get-current-user') != '0':
            raise ExperimentFailure('Only the clean VM primary user is supported')

    def heartbeat(self):
        # Separate run-as process reads a file, not a Binder request to the frozen app.
        return require_heartbeat(json.loads(self.shell('run-as', PACKAGE, 'cat', 'files/heartbeat.json')))

    def probe(self, pid=None):
        args = [REMOTE_PROBE, '--json']
        if pid is not None:
            if type(pid) is not int or not 2 <= pid <= 2147483647:
                raise ExperimentFailure('Invalid fixture PID')
            args += ['--fixture-pid', str(pid)]
        report = json.loads(self.shell(*args))
        if report.get('source') != 'guizang-native-probe' or report.get('read_only') is not True or report.get('android') is not True or report.get('error'):
            raise ExperimentFailure('Invalid Android probe response')
        if report.get('freeze_ready') is not False or report.get('execution') != 'disabled':
            raise ExperimentFailure('Unexpected executing probe')
        return report

    def ams(self, pid):
        # Android16 moved CachedAppOptimizer to 'cao'; older images used settings.
        for subcommand in ('cao', 'settings'):
            dump = self.shell('dumpsys', 'activity', subcommand)
            if re.search(r'^\s*Apps frozen: ', dump, re.M):
                return ams_frozen(dump, pid)
        raise ExperimentFailure('No supported AMS frozen-state diagnostic')

    def freeze(self):
        return self.shell('am', 'freeze', PACKAGE)

    def thaw(self):
        return self.shell('am', 'unfreeze', PACKAGE)

    def passive(self, identity):
        report = self.probe(identity['pid'])
        observed = report['identity']
        if (observed['pid'] != identity['pid'] or observed['uid'] != identity['uid']
                or observed['starttime'] != identity['starttime'] or observed.get('fixture') is not True):
            raise ExperimentFailure('Fixture process lifetime changed')
        return report


def wait_until(action, condition, timeout=5, retry_unavailable=False):
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = action()
        except ExperimentFailure:
            if not retry_unavailable or time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
            continue
        if condition(value):
            return value
        if time.monotonic() >= deadline:
            raise ExperimentFailure('Timed out waiting for corroborated freezer state')
        time.sleep(0.25)


def cleanup_watchdog(adb, marker, result_path):
    # Runs in a separate process/session. A killed coordinator cannot cancel it.
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        if marker.exists():
            return
        time.sleep(0.2)
    result = {'attempted': False}
    try:
        adb.validate_vm()
        result.update(attempted=True, response=adb.thaw())
    except Exception as error:
        result['error'] = type(error).__name__
    result_path.write_text(json.dumps(result))


def run_experiment(args):
    if not args.ack_disposable_vm:
        raise ExperimentFailure('Explicit disposable-VM acknowledgment required; actual approval is separate')
    adb = Adb(args.adb, args.serial)
    adb.validate_vm()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # never merge evidence from old attempts
    report = {'scope': PACKAGE, 'serial': args.serial, 'mode': args.mode, 'passed': False}
    report['fingerprint'] = adb.shell('getprop', 'ro.build.fingerprint')
    binary = Path(args.probe).resolve()
    if not binary.is_file() or binary.read_bytes()[:4] != b'\x7fELF':
        raise ExperimentFailure('An actual compiled Android ELF probe is required')
    report['probe_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
    adb.command('push', str(binary), REMOTE_PROBE)
    # Only the test-owned file executable bit, not security policy or another app's path.
    adb.shell('chmod', '700', REMOTE_PROBE)
    report['capabilities'] = adb.probe()
    (output / 'result.json').write_text(json.dumps(report, indent=2))
    if args.mode == 'probe':
        report['passed'] = True
        (output / 'result.json').write_text(json.dumps(report, indent=2))
        return
    apk = Path(args.apk).resolve()
    if not apk.is_file():
        raise ExperimentFailure('A locally built test fixture APK is required')
    report['apk_sha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
    # Independently inspect the actual APK, not just a nearby source manifest.
    badging = subprocess.run([args.aapt, 'dump', 'badging', str(apk)], check=True, capture_output=True, text=True).stdout
    manifest = subprocess.run([args.aapt, 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'], check=True, capture_output=True, text=True).stdout
    if not re.search(r"^package: name='org.guizang.fixture' ", badging, re.M) or 'uses-permission' in badging:
        raise ExperimentFailure('APK is not the permission-free fixture')
    if re.search(r'E: (service|receiver|provider|activity-alias)\b|sharedUserId', manifest):
        raise ExperimentFailure('Unexpected fixture component or shared UID')
    if adb.shell('pm', 'list', 'packages', PACKAGE).strip():
        raise ExperimentFailure('Fixture already installed; use a fresh disposable VM, do not replace app data')
    adb.command('install', '-t', str(apk), timeout=60)
    help_text = adb.shell('am', 'help')
    if not all(re.search(r'^\s*' + op + r'(?:\s|\[)', help_text, re.M) for op in ('freeze', 'unfreeze')):
        raise ExperimentFailure('This image does not advertise AMS freezer commands; no fallback')
    adb.shell('am', 'start', '-W', '-n', PACKAGE + '/.MainActivity', timeout=30)
    first = wait_until(adb.heartbeat, lambda h: h['counter'] >= 1, retry_unavailable=True)
    adb.shell('input', 'keyevent', 'KEYCODE_HOME')
    time.sleep(0.7)
    before = adb.heartbeat()
    if not same_instance(first, before) or before['counter'] <= first['counter']:
        raise ExperimentFailure('Background heartbeat is not advancing')
    pids = adb.shell('pidof', PACKAGE).split()
    if pids != [str(before['pid'])]:
        raise ExperimentFailure('Fixture process is missing or ambiguous')
    initial = adb.passive(before)
    if initial.get('freezer_observation', {}).get('complete') is not False:
        raise ExperimentFailure('Fixture is already frozen or the completed state is unavailable')
    if not initial['capabilities']['binder_node']:
        raise ExperimentFailure('Binder device observation is absent')
    if adb.ams(before['pid']):
        raise ExperimentFailure('AMS already lists the fixture as frozen')
    report['before'] = {'heartbeat': before, 'probe': initial, 'ams_frozen': False}
    report['exit_info_before'] = adb.shell('dumpsys', 'activity', 'exit-info', PACKAGE)
    (output / 'result.json').write_text(json.dumps(report, indent=2))
    marker = output / 'verified-thaw.marker'
    watchdog_result = output / 'watchdog-result.json'
    watchdog = subprocess.Popen([sys.executable, __file__, '--watchdog', '--serial', args.serial,
                                 '--adb', args.adb, '--marker', str(marker),
                                 '--watchdog-result', str(watchdog_result)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        report['freeze_acceptance'] = adb.freeze()
        frozen = wait_until(lambda: adb.passive(before), lambda p: p.get('freezer_observation', {}).get('complete') is True)
        if not adb.ams(before['pid']):
            raise ExperimentFailure('AMS does not corroborate the frozen fixture')
        frozen_start = adb.heartbeat()
        time.sleep(1.2)
        frozen_end = adb.heartbeat()
        if not same_instance(before, frozen_end) or frozen_start['counter'] != frozen_end['counter']:
            raise ExperimentFailure('Frozen fixture heartbeat did not plateau on the same process')
        if adb.passive(before).get('freezer_observation', {}).get('complete') is not True:
            raise ExperimentFailure('Spontaneous thaw during frozen observation')
        report['frozen'] = {'probe': frozen, 'heartbeat_start': frozen_start, 'heartbeat_end': frozen_end, 'ams_frozen': True}
        (output / 'result.json').write_text(json.dumps(report, indent=2))
        if args.fault_coordinator_exit:
            # Deliberately bypass this process's finally; independent watchdog owns thaw.
            os._exit(73)
        report['thaw_acceptance'] = adb.thaw()
        thawed = wait_until(lambda: adb.passive(before), lambda p: p.get('freezer_observation', {}).get('complete') is False)
        if adb.ams(before['pid']):
            raise ExperimentFailure('AMS still lists the fixture as frozen')
        resumed = wait_until(adb.heartbeat, lambda h: h['counter'] > frozen_end['counter'])
        if not same_instance(before, resumed):
            raise ExperimentFailure('Restart is not a successful thaw')
        report['resumed'] = {'heartbeat': resumed, 'probe': thawed, 'ams_frozen': False}
        report['exit_info_after'] = adb.shell('dumpsys', 'activity', 'exit-info', PACKAGE)
        report['fixture_logcat'] = adb.shell('logcat', '-d', '-v', 'threadtime', '--pid=' + str(before['pid']), '-t', '1000')
        # Kernel completion + heartbeat are recorded; AMS/logcat corroboration remains mandatory.
        report['passed'] = False
        report['result'] = 'AMS_kernel_and_heartbeat_observed; requires_exit_log_review'
        marker.write_text('verified same-instance thaw\n')
        watchdog.wait(timeout=2)
    finally:
        # Bound to the literal fixture package, never an arbitrary or reused PID.
        try:
            report['cleanup_acceptance'] = adb.thaw()
        except Exception as error:
            report['cleanup_error'] = type(error).__name__
        (output / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--mode', choices=['probe', 'freeze-test'], default='probe')
    parser.add_argument('--ack-disposable-vm', action='store_true')
    parser.add_argument('--probe')
    parser.add_argument('--apk')
    parser.add_argument('--aapt', default='aapt')
    parser.add_argument('--fault-coordinator-exit', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--watchdog', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--marker', help=argparse.SUPPRESS)
    parser.add_argument('--watchdog-result', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.watchdog:
            cleanup_watchdog(Adb(args.adb, args.serial), Path(args.marker), Path(args.watchdog_result))
        else:
            if not args.probe or not args.output or (args.mode == 'freeze-test' and not args.apk):
                parser.error('--probe, --output, and --apk for freeze-test are required')
            run_experiment(args)
    except (ExperimentFailure, subprocess.SubprocessError, ValueError, KeyError, OSError) as error:
        print('Experiment stopped: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
