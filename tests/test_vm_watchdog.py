"""Host-only bounded watchdog orchestration. Never launches Android/ADB."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('vm_watchdog_under_test', Path(__file__).parents[1] / 'tools/vm_validate.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


def context():
    return dict(schema=2, package=vm.PACKAGE, serial='emulator-5554',
                boot_id='12345678-1234-1234-1234-123456789abc', token='a'*48,
                trigger_deadline=time.monotonic()+18,
                heartbeat=dict(nonce='x', pid=42, uid=10123, starttime='500', counter=1))


def kernel(frozen):
    return dict(capabilities=dict(binder_node=True, cgroup2_membership=True, self_freezer_node=True),
                freezer_observation=dict(requested=frozen, complete=frozen))


class WatchdogTests(unittest.TestCase):
    def test_real_exit73_and_sigkill_trigger_eof(self):
        # start_watchdog's real executable loads context and performs READY before
        # this owner dies. Missing fake ADB stops cleanup safely after EOF proof.
        for abrupt in (False, True):
            with self.subTest(abrupt=abrupt), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                code = '''
import json, os, pathlib, sys, time
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import vm_validate as vm
root=pathlib.Path(sys.argv[2]); context=json.loads(sys.argv[3])
child, writer, lease, fence=vm.start_watchdog(SimpleNamespace(serial='emulator-5554',adb='/nonexistent-guizang-test-adb'),root,context)
(root/'owner-ready').write_text(str(child.pid))
if sys.argv[4]=='exit': os._exit(73)
time.sleep(30)
'''
                owner = subprocess.Popen([sys.executable, '-c', code, str(Path(vm.__file__).parent),
                                          directory, json.dumps(context()), 'kill' if abrupt else 'exit'])
                try:
                    deadline=time.monotonic()+4
                    while not (root/'owner-ready').exists() and time.monotonic()<deadline:
                        time.sleep(.02)
                    self.assertTrue((root/'owner-ready').exists())
                    if abrupt: owner.kill()
                    self.assertEqual(owner.wait(timeout=3), -signal.SIGKILL if abrupt else 73)
                    deadline=time.monotonic()+4
                    while not (root/'watchdog-result.json').exists() and time.monotonic()<deadline:
                        time.sleep(.02)
                    report=json.loads((root/'watchdog-result.json').read_text())
                    self.assertEqual(report['trigger'],'owner_eof')
                    self.assertFalse(report['verified_thaw'])
                finally:
                    if owner.poll() is None: owner.kill(); owner.wait()

    def test_real_ready_completion_and_no_adb(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); ctx=context()
            child, writer, _, _=vm.start_watchdog(SimpleNamespace(serial='emulator-5554',adb='/never-called'),root,ctx)
            vm.record_completion(root/'verified-thaw.marker',ctx)
            os.close(writer)
            self.assertEqual(child.wait(timeout=3),0)
            report=json.loads((root/'watchdog-result.json').read_text())
            self.assertTrue(report['cancelled_after_verified_thaw'])
            self.assertFalse(report['attempted'])

    def test_invalid_context_fails_readiness_before_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx=context();ctx['package']='system.other'
            with self.assertRaisesRegex(vm.ExperimentFailure,'readiness'):
                vm.start_watchdog(SimpleNamespace(serial='emulator-5554',adb='/never-called'),Path(directory),ctx)

    def test_cloexec_owner_writer_not_inherited_by_command_child(self):
        read, write=os.pipe()
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(3)'],close_fds=True)
        try:
            self.assertFalse(os.get_inheritable(write))
            os.close(write)
            with tempfile.TemporaryDirectory() as directory:
                started=time.monotonic()
                self.assertEqual(vm.wait_for_owner(read,Path(directory)/'marker',context()),'owner_eof')
                self.assertLess(time.monotonic()-started,1)
                self.assertIsNone(child.poll())
        finally:
            os.close(read);child.terminate();child.wait(timeout=3)

    def test_absolute_deadline_triggers_with_live_owner(self):
        read,write=os.pipe()
        try:
            with tempfile.TemporaryDirectory() as directory:
                ctx=context();ctx['trigger_deadline']=time.monotonic()+.04
                self.assertEqual(vm.wait_for_owner(read,Path(directory)/'marker',ctx),'absolute_deadline')
        finally: os.close(read);os.close(write)

    def test_marker_requires_exact_nonce_token_and_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'marker';ctx=context()
            vm.record_completion(marker,ctx)
            self.assertTrue(vm.completion_matches(marker,ctx))
            ctx['heartbeat']['nonce']='replacement'
            with self.assertRaises(vm.ExperimentFailure):vm.completion_matches(marker,ctx)

    def test_late_freeze_fence_and_expired_lease_never_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lease=root/'lock';lease.touch();fence=root/'fence';adb=Mock();adb.deadline=None
            fence.write_text('watchdog terminal fence')
            with self.assertRaises(vm.ExperimentFailure):vm.submit_freeze(adb,lease,fence,time.monotonic()+1)
            fence.unlink()
            with self.assertRaises(vm.ExperimentFailure):vm.submit_freeze(adb,lease,fence,time.monotonic()-1)
            adb.freeze.assert_not_called()

    def test_cleanup_adb_uses_cumulative_deadline_and_no_inherited_fds(self):
        run=Mock(return_value=SimpleNamespace(returncode=0,stdout='ok',stderr=''))
        adb=vm.Adb('adb','emulator-5554',run=run);adb.deadline=time.monotonic()+.5
        adb.command('shell','id','-u',timeout=15)
        self.assertLessEqual(run.call_args.kwargs['timeout'],.5)
        self.assertTrue(run.call_args.kwargs['close_fds'])
        adb.deadline=time.monotonic()-1
        with self.assertRaisesRegex(vm.ExperimentFailure,'deadline'):adb.thaw()
        self.assertEqual(run.call_count,1)

    def test_transition_requires_one_fresh_reason0_in_command_window(self):
        good='1000.500000 1 2 D ActivityManager: sync unfroze 42 org.guizang.fixture for 0'
        self.assertIn('fresh_reason_zero_transition',vm.review_watchdog_transition('',good,42,1000.4,1000.6))
        for old,new,start,end in [(good,good,1000.4,1000.6),('',good.replace('for 0','for 12'),1000.4,1000.6),
                                  ('',good,1000.6,1000.7),('',good+'\n'+good.replace('.500000','.550000'),1000.4,1000.6),
                                  ('',good.replace('42','43'),1000.4,1000.6),
                                  ('','1000.450000 1 2 D ActivityManager: quick sync unfreeze 42 for 12\n'+good,1000.4,1000.6)]:
            with self.assertRaises(vm.ExperimentFailure):vm.review_watchdog_transition(old,new,42,start,end)

    def run_mock_cleanup(self, root, frozen=True, thaw_error=False, wrong_boot=False, wrong_nonce=False, wrong_start=False, invalid_marker=False):
        ctx=context();adb=Mock(serial='emulator-5554');adb.boot_id.return_value='replacement-boot' if wrong_boot else ctx['boot_id']
        adb.heartbeat.return_value=dict(ctx['heartbeat'], **({'nonce':'replacement'} if wrong_nonce else {'starttime':'501'} if wrong_start else {}));adb.passive.return_value=kernel(frozen);adb.ams.return_value=frozen
        adb.logs.side_effect=['','1000.500000 1 2 D ActivityManager: sync unfroze 42 org.guizang.fixture for 0']
        adb.guest_time.side_effect=[1000.4,1000.6]
        if thaw_error:adb.thaw.side_effect=vm.AdbFailure(['shell','am','unfreeze'],'','closed')
        else:adb.thaw.return_value='accepted'
        if invalid_marker: (root/'marker').write_text('malformed')
        death_read,death_write=os.pipe();ready_read,ready_write=os.pipe();lease=root/'lock';lease.touch()
        try:
            with patch.object(vm,'wait_for_owner',return_value='owner_eof'), patch.object(vm,'observe_thaw',return_value={'same_instance':True}):
                vm.cleanup_watchdog(adb,root/'marker',root/'result.json',ctx,death_read,ready_write,lease,root/'fence')
            return json.loads((root/'result.json').read_text()),adb
        finally:os.close(death_write);os.close(ready_read)

    def test_already_thawed_cleans_without_causal_credit(self):
        for frozen in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                result,adb=self.run_mock_cleanup(Path(directory),frozen=frozen)
                self.assertTrue(result['attempted']);self.assertEqual(result['verified_thaw'],frozen)
                adb.thaw.assert_called_once()

    def test_attempt_durable_when_thaw_throws(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);result,_=self.run_mock_cleanup(root,thaw_error=True)
            self.assertTrue(result['attempted']);self.assertFalse(result['verified_thaw'])
            self.assertTrue(json.loads((root/'result.attempt.json').read_text())['attempted'])

    def test_real_late_freeze_race_is_fenced_under_shared_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);lease=root/'lock';lease.touch()
            code='''
import pathlib,sys,time
sys.path.insert(0,sys.argv[1]);import vm_validate as vm
root=pathlib.Path(sys.argv[2])
class Adb:
 deadline=None
 def freeze(self): (root/'unexpected-freeze').write_text('unsafe')
(root/'waiting').write_text('ready')
try: vm.submit_freeze(Adb(),root/'lock',root/'fence',time.monotonic()+3)
except vm.ExperimentFailure: sys.exit(7)
'''
            with lease.open('r+') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                child=subprocess.Popen([sys.executable,'-c',code,str(Path(vm.__file__).parent),directory])
                try:
                    deadline=time.monotonic()+2
                    while not (root/'waiting').exists() and time.monotonic()<deadline:time.sleep(.01)
                    self.assertTrue((root/'waiting').exists())
                    (root/'fence').write_text('cleanup owns terminal state')
                    fcntl.flock(lock,fcntl.LOCK_UN)
                    self.assertEqual(child.wait(timeout=3),7)
                    self.assertFalse((root/'unexpected-freeze').exists())
                finally:
                    if child.poll() is None:child.kill();child.wait()

    def test_replacement_boot_or_instance_never_receives_thaw(self):
        for change in ('wrong_boot','wrong_nonce','wrong_start'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                result,adb=self.run_mock_cleanup(Path(directory),**{change:True})
                self.assertFalse(result['attempted']);self.assertFalse(result['verified_thaw'])
                adb.thaw.assert_not_called()

    def test_malformed_marker_cannot_cancel_cleanup_or_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            result,adb=self.run_mock_cleanup(Path(directory),invalid_marker=True)
            self.assertTrue(result['attempted']);self.assertFalse(result['verified_thaw'])
            self.assertIn('marker_error',result);adb.thaw.assert_called_once()
        read,write=os.pipe()
        try:
            with tempfile.TemporaryDirectory() as directory:
                marker=Path(directory)/'marker';marker.write_text('{}')
                self.assertEqual(vm.wait_for_owner(read,marker,context()),'invalid_completion_marker')
        finally:os.close(read);os.close(write)
