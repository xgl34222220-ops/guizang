#!/usr/bin/env python3
"""Bounded, separately authorized disposable-AVD fixture experiment.

No automatic Root elevation, image patches, global settings, or raw cgroup writes.
The acknowledgment flag is a guardrail, never a substitute for user authorization.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import select
import secrets
import subprocess
import sys
import time

PACKAGE = 'org.guizang.fixture'
REMOTE_PROBE = '/data/local/tmp/guizang-probe'
EXIT_HEADER = 'ACTIVITY MANAGER PROCESS EXIT INFO (dumpsys activity exit-info)'


class ExperimentFailure(RuntimeError):
    pass


class AdbFailure(ExperimentFailure):
    def __init__(self, args, stdout, stderr):
        self.detail = (stdout + '\n' + stderr).strip()
        super().__init__('ADB operation failed: ' + ' '.join(map(str, args[:3])) + ': ' + self.detail)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
    def __init__(self, executable, serial, run=subprocess.run, evidence=None):
        self.executable, self.serial, self.run = executable, validate_serial(serial), run
        self.evidence = Path(evidence) if evidence else None
        self.deadline = None

    def command(self, *args, timeout=15, retain=None):
        record = {'started_at': timestamp(), 'args': list(map(str, args))}
        try:
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise ExperimentFailure('Bounded cleanup I/O deadline exceeded')
                timeout = min(timeout, remaining)
            result = self.run([self.executable, '-s', self.serial, *map(str, args)],
                              check=False, capture_output=True, text=True, timeout=timeout, close_fds=True)
            stdout = retain(result.stdout) if retain else result.stdout
            record.update(returncode=result.returncode, stdout=stdout, stderr=result.stderr)
            if result.returncode:
                raise AdbFailure(args, result.stdout, result.stderr)
            return stdout.strip()
        except Exception as error:
            record['error'] = str(error)
            raise
        finally:
            record['finished_at'] = timestamp()
            if self.evidence:
                with self.evidence.open('a') as stream:
                    stream.write(json.dumps(record) + '\n')

    def shell(self, *args, **kwargs):
        return self.command('shell', *args, **kwargs)

    def boot_id(self):
        value = self.shell('cat', '/proc/sys/kernel/random/boot_id')
        if not re.fullmatch(r'[a-f0-9-]{36}', value):
            raise ExperimentFailure('Missing VM boot identity')
        return value

    def validate_vm(self):
        if self.shell('getprop', 'ro.kernel.qemu') != '1':
            raise ExperimentFailure('Selected target is not a verified emulator')
        if self.shell('id', '-u') != '0':
            raise ExperimentFailure('Debug Root is not active; obtain approval before adb root')
        if self.shell('am', 'get-current-user') != '0':
            raise ExperimentFailure('Only the clean VM primary user is supported')

    def heartbeat(self):
        # Already-verified debug Root reads only our fixed fixture file. Do not
        # launch run-as into the fixture UID/cgroup during frozen observation.
        try:
            return require_heartbeat(json.loads(self.shell('cat', '/data/user/0/' + PACKAGE + '/files/heartbeat.json')))
        except (ValueError, TypeError) as error:
            raise ExperimentFailure('Fixture heartbeat unavailable') from error

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
        # Android16 moved CachedAppOptimizer to 'cao'; API35 normally uses settings.
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

    def guest_time(self):
        value = self.shell('date', '+%s.%N')
        if not re.fullmatch(r'[0-9]{10}\.[0-9]{9}', value):
            raise ExperimentFailure('Guest epoch nanosecond clock unavailable')
        return float(value)

    def logs(self, pid):
        # Keep only this fixture's lines, including system_server freezer messages.
        pattern = re.compile(r'(?<!\d)' + str(pid) + r'(?!\d)|' + re.escape(PACKAGE))
        return self.shell('logcat', '-d', '-v', 'epoch', '-v', 'usec', '-b', 'main,system,crash',
                          '-t', '10000', 'ActivityManager:D', 'AndroidRuntime:E', 'libc:F',
                          'DEBUG:F', '*:S', retain=lambda text: '\n'.join(
                              line for line in text.splitlines() if pattern.search(line)))


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



def background_ready(heartbeat):
    lifecycle = heartbeat.get('lifecycle')
    if not isinstance(lifecycle, list) or not lifecycle or not isinstance(lifecycle[-1], dict):
        return False
    last = lifecycle[-1]
    return (last.get('name') == 'onStop'
            and type(last.get('sequence')) is int
            and last['sequence'] == heartbeat.get('lifecycle_sequence')
            and heartbeat.get('prior_write_errors') == 0)


def await_background(adb, first):
    previous = None
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        current = adb.heartbeat()
        if not same_instance(first, current):
            raise ExperimentFailure('Background heartbeat changed process')
        if background_ready(current):
            if (previous is not None
                    and current['lifecycle_sequence'] == previous['lifecycle_sequence']
                    and current['counter'] >= previous['counter'] + 2):
                return current
            if previous is None or current['lifecycle_sequence'] != previous['lifecycle_sequence']:
                previous = current
        else:
            previous = None
        time.sleep(0.25)
    raise ExperimentFailure('Fixture did not reach stable stopped lifecycle with advancing heartbeat')


def require_kernel(report, frozen):
    capabilities = report.get('capabilities', {})
    observation = report.get('freezer_observation', {})
    if (capabilities.get('binder_node') is not True
            or capabilities.get('cgroup2_membership') is not True
            or capabilities.get('self_freezer_node') is not True
            or observation.get('complete') is not frozen
            or observation.get('requested') is not frozen):
        raise ExperimentFailure('Missing or inconsistent Binder/cgroup freezer evidence')


def installed_apk_hash(adb):
    paths = adb.shell('pm', 'path', PACKAGE).splitlines()
    if len(paths) != 1 or not re.fullmatch(r'package:/data/app/[a-zA-Z0-9_+=~./-]+/base\.apk', paths[0]):
        raise ExperimentFailure('Installed fixture APK path missing or ambiguous')
    remote = paths[0][len('package:'):]
    value = adb.shell('sha256sum', remote).split()
    if len(value) != 2 or not re.fullmatch(r'[0-9a-f]{64}', value[0]) or value[1] != remote:
        raise ExperimentFailure('Installed fixture APK hash unavailable')
    return value[0]


def prepare_fixture(adb, apk, boot_id, receipt_path=None, reuse=False):
    digest = sha256(apk)
    installed = bool(adb.shell('pm', 'list', 'packages', PACKAGE).strip())
    expected = {'schema': 1, 'package': PACKAGE, 'serial': adb.serial,
                'boot_id': boot_id, 'apk_sha256': digest, 'installed_by_experiment': True}
    if reuse:
        if not installed or not receipt_path or not Path(receipt_path).is_file():
            raise ExperimentFailure('Reuse requires this VM session installation receipt')
        receipt = json.loads(Path(receipt_path).read_text())
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise ExperimentFailure('Fixture reuse receipt does not match this APK and VM boot')
        if installed_apk_hash(adb) != digest:
            raise ExperimentFailure('Installed fixture APK differs from this build')
        return {**expected, 'reused_without_reinstall': True}
    if installed:
        raise ExperimentFailure('Fixture already installed; never replace unrelated app data')
    if receipt_path and Path(receipt_path).exists():
        raise ExperimentFailure('Installation receipt already exists')
    adb.command('install', '-t', str(apk), timeout=60)
    if installed_apk_hash(adb) != digest:
        raise ExperimentFailure('Installed fixture APK hash mismatch')
    receipt = {**expected, 'installed_at': timestamp()}
    if receipt_path:
        # Exclusive creation prevents accidental replacement of session evidence.
        with Path(receipt_path).open('x') as stream:
            json.dump(receipt, stream, indent=2)
    return receipt


def observe_thaw(adb, before, counter):
    thawed = wait_until(lambda: adb.passive(before),
                        lambda p: p.get('freezer_observation', {}).get('complete') is False)
    require_kernel(thawed, False)
    if adb.ams(before['pid']):
        raise ExperimentFailure('AMS still lists the fixture as frozen')
    resumed = wait_until(adb.heartbeat, lambda h: h['counter'] > counter)
    if not same_instance(before, resumed):
        raise ExperimentFailure('Restart is not a successful thaw')
    adb.passive(resumed)
    return {'observed_at': timestamp(), 'heartbeat': resumed, 'probe': thawed, 'ams_frozen': False}


def diagnostic_review(exit_before, exit_after, logs_before, logs_after, pid):
    # Empty history is valid only with the actual dumpsys header. Never infer it
    # from an empty command response. A fresh fixture must have no historic exits.
    for dump in (exit_before, exit_after):
        if EXIT_HEADER not in dump or 'Historical Process Exit' in dump:
            raise ExperimentFailure('Exit history absent, unrecognized, or contains a fixture exit')
    previous = set(logs_before.splitlines())
    lines = [line for line in logs_after.splitlines() if line not in previous]
    new = '\n'.join(lines)
    target = str(pid) + r'\s+' + re.escape(PACKAGE) + r'\b'
    if not re.search(r'\bfreezing\s+' + target, new) or not re.search(r'\bunfroze\s+' + target, new):
        raise ExperimentFailure('Missing positive fixture freeze/thaw framework log evidence')
    failure = re.compile(r'Unable to (?:un)?freeze|FATAL EXCEPTION|ANR in|\bKilling\b|'
                         r'(?:binder|freezer).*(?:fail|error)|(?:fail|error).*binder', re.I)
    if any(failure.search(line) for line in lines):
        raise ExperimentFailure('Fixture logs contain Binder/freezer/exit errors')
    return {'checked_at': timestamp(), 'framework_freeze_and_thaw_logs': True,
            'no_recorded_fixture_exit': True, 'no_scoped_error': True,
            'new_scoped_log_lines': lines,
            'binder_evidence': 'device presence plus AMS-managed transition; no direct Binder ioctl probe'}


def collect_diagnostics(adb, report):
    pid = report['before']['heartbeat']['pid']
    report['exit_info_after'] = adb.shell('dumpsys', 'activity', 'exit-info', PACKAGE)
    report['fixture_logcat_after'] = adb.logs(pid)
    report['diagnostic_review'] = diagnostic_review(
        report['exit_info_before'], report['exit_info_after'],
        report['fixture_logcat_before'], report['fixture_logcat_after'], pid)


WATCHDOG_TRIGGER_SECONDS = 18
WATCHDOG_IO_SECONDS = 20


def validate_watchdog_context(context, serial):
    if (context.get('schema') != 2 or context.get('package') != PACKAGE
            or context.get('serial') != serial
            or not re.fullmatch(r'[a-f0-9-]{36}', context.get('boot_id', ''))
            or not re.fullmatch(r'[a-f0-9]{48}', context.get('token', ''))
            or type(context.get('trigger_deadline')) not in (int, float)
            or not 0 < context['trigger_deadline'] - time.monotonic() <= WATCHDOG_TRIGGER_SECONDS):
        raise ExperimentFailure('Invalid watchdog scope or deadline')
    require_heartbeat(context['heartbeat'])
    return context


def completion_value(context):
    return {'token': context['token'], 'boot_id': context['boot_id'],
            'identity': {key: context['heartbeat'][key] for key in ('pid', 'uid', 'starttime', 'nonce')}}


def completion_matches(marker, context):
    if not marker.exists():
        return False
    if marker.is_symlink() or json.loads(marker.read_text()) != completion_value(context):
        raise ExperimentFailure('Completion marker identity mismatch')
    return True


def record_completion(marker, context):
    # Caller has just verified kernel, AMS and advancing same-instance heartbeat.
    save_json(marker, completion_value(context))


def wait_for_owner(death_fd, marker, context):
    while True:
        try:
            if completion_matches(marker, context):
                return 'verified_completion'
        except (ExperimentFailure, ValueError, OSError):
            return 'invalid_completion_marker'
        remaining = context['trigger_deadline'] - time.monotonic()
        if remaining <= 0:
            return 'absolute_deadline'
        readable, _, _ = select.select([death_fd], [], [], min(0.1, remaining))
        if readable:
            if os.read(death_fd, 1) != b'':
                raise ExperimentFailure('Unexpected data on owner death pipe')
            return 'owner_eof'


def acquire_lease(stream, deadline):
    while True:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise ExperimentFailure('Freeze/cleanup lease deadline exceeded')
            time.sleep(0.02)


def submit_freeze(adb, lease, fence, deadline):
    with lease.open('r+') as stream:
        acquire_lease(stream, deadline)
        if fence.exists() or time.monotonic() >= deadline:
            raise ExperimentFailure('Watchdog fenced late freeze submission')
        # Client timeout bounds this lease; ambiguous timeout remains FAIL and
        # the outer runner destroys the disposable VM rather than claiming safety.
        old = adb.deadline
        adb.deadline = deadline
        try:
            return adb.freeze()
        finally:
            adb.deadline = old


def review_watchdog_transition(before_logs, after_logs, pid, started, finished):
    if not started <= finished:
        raise ExperimentFailure('Guest command clock moved backwards')
    old = set(before_logs.splitlines())
    fresh = [line for line in after_logs.splitlines() if line not in old]
    target = str(pid) + r'\s+' + re.escape(PACKAGE) + r'\b'
    # Quick-unfreeze can thaw kernel/Binder without clearing AMS bookkeeping.
    # It lacks the package in AOSP logs, so include exact PID-only transitions.
    pid_token = r'(?<![0-9])' + str(pid) + r'(?![0-9])'
    transitions = [line for line in fresh if re.search(pid_token, line)
                   and re.search(r'\b(?:unfroze|unfreeze|freezing|froze)\b', line)]
    if len(transitions) != 1:
        raise ExperimentFailure('Missing or ambiguous fresh watchdog transition')
    line = transitions[0]
    match = re.match(r'^\s*([0-9]+\.[0-9]+)\s+', line)
    if (not match or not re.search(r'\bsync unfroze\s+' + target + r' for 0\s*$', line)
            or not started <= float(match[1]) <= finished):
        raise ExperimentFailure('Watchdog transition is natural, stale, or outside command window')
    return {'fresh_reason_zero_transition': line, 'guest_command_window': [started, finished],
            'attribution': 'API35 shell reason 0, sole cleanup writer, frozen handoff, bounded fresh log'}


def cleanup_watchdog(adb, marker, result_path, context, death_fd, ready_fd, lease, fence):
    result = {'started_at': timestamp(), 'attempted': False, 'verified_thaw': False,
              'trigger_budget_seconds': WATCHDOG_TRIGGER_SECONDS,
              'cleanup_io_budget_seconds': WATCHDOG_IO_SECONDS}
    try:
        # Deserialize exactly once before acknowledging readiness. The random
        # token and identity are never reloaded from coordinator-writable files.
        context = validate_watchdog_context(context, adb.serial)
        os.write(ready_fd, b'R')
        os.close(ready_fd)
        ready_fd = None
        result['ready_at'] = timestamp()
        trigger = wait_for_owner(death_fd, marker, context)
        result.update(trigger=trigger, triggered_at=timestamp())
        if trigger == 'verified_completion':
            result['cancelled_after_verified_thaw'] = True
            return
        deadline = time.monotonic() + WATCHDOG_IO_SECONDS
        adb.deadline = deadline
        with lease.open('r+') as stream:
            acquire_lease(stream, deadline)
            # Fence is set under the same lock used by all freeze submissions.
            fence.write_text('watchdog owns terminal cleanup\n')
            try:
                completed = completion_matches(marker, context)
            except (ExperimentFailure, ValueError, OSError) as error:
                result['marker_error'] = str(error)
                completed = False
            if completed:
                result['cancelled_after_verified_thaw'] = True
                return
            adb.validate_vm()
            if adb.boot_id() != context['boot_id']:
                raise ExperimentFailure('Watchdog refuses a replacement VM boot')
            before = context['heartbeat']
            # Baseline precedes every handoff observation; never erase a
            # competing transition by sampling logs after kernel/AMS checks.
            logs_before = adb.logs(before['pid'])
            result['logs_before'] = logs_before
            initial = adb.passive(before)
            initial_ams = adb.ams(before['pid'])
            result['before_cleanup'] = {'probe': initial, 'ams_frozen': initial_ams}
            current = adb.heartbeat()
            if not same_instance(before, current):
                raise ExperimentFailure('Watchdog refuses a replacement fixture process')
            started = adb.guest_time()
            result.update(attempted=True, command_started_at=timestamp())
            save_json(result_path.with_suffix('.attempt.json'), result)
            # Attempt is durable even if this command throws or times out.
            result['response'] = adb.thaw()
            finished = adb.guest_time()
            result['resumed'] = observe_thaw(adb, before, current['counter'])
            logs_after = adb.logs(before['pid'])
            result.update(logs_before=logs_before, logs_after=logs_after)
            require_kernel(initial, True)
            if not initial_ams:
                raise ExperimentFailure('Watchdog found fixture already absent from AMS frozen set')
            result['transition_review'] = review_watchdog_transition(
                logs_before, logs_after, before['pid'], started, finished)
            if result.get('marker_error'):
                raise ExperimentFailure('Invalid completion marker; cleanup performed without pass credit')
            result['verified_thaw'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        if ready_fd is not None:
            os.close(ready_fd)
        os.close(death_fd)
        result['finished_at'] = timestamp()
        save_json(result_path, result)


def start_watchdog(args, output, context):
    death_read, death_write = os.pipe()
    ready_read, ready_write = os.pipe()
    child = None
    lease, fence = output / 'freeze-cleanup.lock', output / 'cleanup-fence'
    lease.touch(exist_ok=False)
    try:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--watchdog',
            '--serial', args.serial, '--adb', args.adb, '--marker', str(output / 'verified-thaw.marker'),
            '--watchdog-result', str(output / 'watchdog-result.json'),
            '--watchdog-context-json', json.dumps(context),
            '--death-fd', str(death_read), '--ready-fd', str(ready_write),
            '--lease', str(lease), '--fence', str(fence)],
            pass_fds=(death_read, ready_write), close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        os.close(death_read); death_read = None
        os.close(ready_write); ready_write = None
        ready, _, _ = select.select([ready_read], [], [], 3)
        if not ready or os.read(ready_read, 1) != b'R' or child.poll() is not None:
            raise ExperimentFailure('Independent watchdog failed readiness handshake; no freeze')
        return child, death_write, lease, fence
    except BaseException:
        os.close(death_write)
        # EOF wakes any successfully started watchdog; no freeze has occurred.
        if child is not None:
            child.wait(timeout=WATCHDOG_IO_SECONDS + 4)
        raise
    finally:
        os.close(ready_read)
        for fd in (death_read, ready_write):
            if fd is not None:
                os.close(fd)


def run_experiment(args):
    if not args.ack_disposable_vm:
        raise ExperimentFailure('Disposable-VM acknowledgment required; actual approval is separate')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'scope': PACKAGE, 'serial': args.serial, 'mode': args.mode,
              'started_at': timestamp(), 'passed': False, 'result': 'INCOMPLETE'}
    adb = Adb(args.adb, args.serial, evidence=output / 'adb-commands.jsonl')
    watchdog = None
    death_write = None
    cleanup_needed = False
    try:
        adb.validate_vm()
        report['boot_id'] = adb.boot_id()
        report['fingerprint'] = adb.shell('getprop', 'ro.build.fingerprint')
        binary = Path(args.probe).resolve()
        if not binary.is_file() or binary.read_bytes()[:4] != b'\x7fELF':
            raise ExperimentFailure('An actual compiled Android ELF probe is required')
        report['probe_sha256'] = sha256(binary)
        adb.command('push', str(binary), REMOTE_PROBE)
        adb.shell('chmod', '700', REMOTE_PROBE)  # Our uploaded file only.
        report['capabilities'] = adb.probe()
        if args.mode == 'probe':
            report.update(passed=True, result='READ_ONLY_PROBE_COMPLETE')
            return report
        apk = Path(args.apk).resolve()
        if not apk.is_file():
            raise ExperimentFailure('A locally built test fixture APK is required')
        report['apk_sha256'] = sha256(apk)
        badging = subprocess.run([args.aapt, 'dump', 'badging', str(apk)], check=True,
                                 capture_output=True, text=True, timeout=20).stdout
        manifest = subprocess.run([args.aapt, 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'],
                                  check=True, capture_output=True, text=True, timeout=20).stdout
        (output / 'apk-badging.txt').write_text(badging)
        (output / 'apk-manifest.txt').write_text(manifest)
        if not re.search(r"^package: name='org.guizang.fixture' ", badging, re.M) or 'uses-permission' in badging:
            raise ExperimentFailure('APK is not the permission-free fixture')
        if re.search(r'E: (service|receiver|provider|activity-alias)\b|sharedUserId', manifest):
            raise ExperimentFailure('Unexpected fixture component or shared UID')
        report['installation'] = prepare_fixture(adb, apk, report['boot_id'], args.receipt, args.reuse_fixture)
        help_text = adb.shell('am', 'help')
        if not all(re.search(r'^\s*' + op + r'(?:\s|\[)', help_text, re.M) for op in ('freeze', 'unfreeze')):
            raise ExperimentFailure('Image does not advertise AMS freezer commands; no fallback')
        adb.shell('am', 'start', '-W', '-n', PACKAGE + '/.MainActivity', timeout=30)
        first = wait_until(adb.heartbeat, lambda h: h['counter'] >= 1, retry_unavailable=True)
        adb.shell('input', 'keyevent', 'KEYCODE_HOME')
        before = await_background(adb, first)
        if not same_instance(first, before):
            raise ExperimentFailure('Background heartbeat changed process')
        if adb.shell('pidof', PACKAGE).split() != [str(before['pid'])]:
            raise ExperimentFailure('Fixture process is missing or ambiguous')
        initial = adb.passive(before)
        require_kernel(initial, False)
        if adb.ams(before['pid']):
            raise ExperimentFailure('AMS already lists the fixture as frozen')
        report['before'] = {'observed_at': timestamp(), 'heartbeat': before, 'probe': initial, 'ams_frozen': False}
        report['exit_info_before'] = adb.shell('dumpsys', 'activity', 'exit-info', PACKAGE)
        report['fixture_logcat_before'] = adb.logs(before['pid'])
        if EXIT_HEADER not in report['exit_info_before'] or 'Historical Process Exit' in report['exit_info_before']:
            raise ExperimentFailure('Initial fixture exit history is not clean and observable')
        marker = output / 'verified-thaw.marker'
        context = {'schema': 2, 'package': PACKAGE, 'serial': args.serial,
                   'boot_id': report['boot_id'], 'heartbeat': before,
                   'token': secrets.token_hex(24),
                   'trigger_deadline': time.monotonic() + WATCHDOG_TRIGGER_SECONDS}
        save_json(output / 'watchdog-context.json', context)
        save_json(output / 'result.json', report)
        watchdog, death_write, lease, fence = start_watchdog(args, output, context)
        report['watchdog_pid'] = watchdog.pid
        report['watchdog_ready'] = True
        cleanup_needed = True
        report['freeze_acceptance'] = submit_freeze(adb, lease, fence, context['trigger_deadline'])
        frozen = wait_until(lambda: adb.passive(before), lambda p: p.get('freezer_observation', {}).get('complete') is True)
        require_kernel(frozen, True)
        if not adb.ams(before['pid']):
            raise ExperimentFailure('AMS does not corroborate the frozen fixture')
        frozen_start = adb.heartbeat()
        time.sleep(1.2)
        frozen_end = adb.heartbeat()
        report['frozen_observation'] = {'probe': frozen, 'heartbeat_start': frozen_start,
                                        'heartbeat_end': frozen_end}
        if (not same_instance(before, frozen_start) or not same_instance(before, frozen_end)
                or frozen_start['counter'] != frozen_end['counter']):
            raise ExperimentFailure('Frozen fixture heartbeat did not plateau on the same process')
        require_kernel(adb.passive(before), True)
        if not adb.ams(before['pid']):
            raise ExperimentFailure('Spontaneous AMS thaw during frozen observation')
        report['frozen'] = {'observed_at': timestamp(), 'probe': frozen, 'heartbeat_start': frozen_start,
                            'heartbeat_end': frozen_end, 'ams_frozen': True}
        save_json(output / 'result.json', report)
        if args.fault_coordinator_exit:
            os._exit(73)  # Intentionally bypass finally; independent watchdog owns recovery.
        with lease.open('r+') as stream:
            acquire_lease(stream, context['trigger_deadline'])
            if fence.exists():
                raise ExperimentFailure('Watchdog already owns cleanup')
            adb.deadline = time.monotonic() + WATCHDOG_IO_SECONDS
            try:
                report['thaw_acceptance'] = adb.thaw()
                report['resumed'] = observe_thaw(adb, before, frozen_end['counter'])
                collect_diagnostics(adb, report)
                record_completion(marker, context)
            finally:
                adb.deadline = None
        os.close(death_write)
        death_write = None
        watchdog.wait(timeout=3)
        report['watchdog_exit'] = watchdog.returncode
        watchdog_result = json.loads((output / 'watchdog-result.json').read_text())
        if (watchdog.returncode != 0
                or watchdog_result.get('cancelled_after_verified_thaw') is not True
                or watchdog_result.get('attempted') is not False):
            raise ExperimentFailure('Cleanup watchdog completion was not cleanly acknowledged')
        cleanup_needed = False
        report.update(passed=True, result='BOUNDED_FIXTURE_EVIDENCE_PASS')
        return report
    except BaseException as error:
        report.update(passed=False, result='FAIL', error=str(error))
        raise
    finally:
        if cleanup_needed:
            # The independent process is the sole error-cleanup writer. Closing
            # this CLOEXEC pipe cannot leave coordinator/ADB writers alive.
            if death_write is not None:
                os.close(death_write)
                death_write = None
            if watchdog:
                try:
                    watchdog.wait(timeout=WATCHDOG_IO_SECONDS + 5)
                    report['watchdog_exit'] = watchdog.returncode
                    cleanup = json.loads((output / 'watchdog-result.json').read_text())
                    if cleanup.get('resumed'):
                        report['cleanup_resumed'] = cleanup['resumed']
                    if cleanup.get('error'):
                        report['cleanup_error'] = cleanup['error']
                except Exception as error:
                    report['cleanup_error'] = str(error)
        if death_write is not None:
            os.close(death_write)
            death_write = None
        if report.get('before'):
            try:
                report['fixture_logcat_terminal'] = adb.logs(report['before']['heartbeat']['pid'])
                report['exit_info_terminal'] = adb.shell('dumpsys', 'activity', 'exit-info', PACKAGE)
            except Exception as error:
                report['terminal_diagnostic_error'] = str(error)
        report['finished_at'] = timestamp()
        save_json(output / 'result.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--mode', choices=['probe', 'freeze-test'], default='probe')
    parser.add_argument('--ack-disposable-vm', action='store_true')
    parser.add_argument('--probe')
    parser.add_argument('--apk')
    parser.add_argument('--aapt', default='aapt')
    parser.add_argument('--receipt')
    parser.add_argument('--reuse-fixture', action='store_true')
    parser.add_argument('--fault-coordinator-exit', action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--watchdog', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--marker', help=argparse.SUPPRESS)
    parser.add_argument('--watchdog-result', help=argparse.SUPPRESS)
    parser.add_argument('--watchdog-context-json', help=argparse.SUPPRESS)
    parser.add_argument('--death-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--ready-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--lease', help=argparse.SUPPRESS)
    parser.add_argument('--fence', help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.watchdog:
            cleanup_watchdog(Adb(args.adb, args.serial, evidence=Path(args.watchdog_result).with_suffix('.jsonl')),
                             Path(args.marker), Path(args.watchdog_result), json.loads(args.watchdog_context_json),
                             args.death_fd, args.ready_fd, Path(args.lease), Path(args.fence))
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
