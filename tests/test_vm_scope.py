import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
spec = importlib.util.spec_from_file_location('vm_validate', Path(__file__).parents[1] / 'tools/vm_validate.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)
sys.modules['vm_validate'] = vm
runner_spec = importlib.util.spec_from_file_location('vm_runner', Path(__file__).parents[1] / 'tools/vm_runner.py')
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)


class VmScopeTests(unittest.TestCase):
    def test_ams_section_exact_identity_and_fail_closed(self):
        dump='CachedAppOptimizer settings\n  Apps frozen: 2\n    20: 42 org.guizang.fixture\n    30: 66 com.android.other\nend\n'
        self.assertTrue(vm.ams_frozen(dump,42))
        self.assertFalse(vm.ams_frozen(dump,43))
        self.assertFalse(vm.ams_frozen('  Apps frozen: 0\n',42))
        for invalid in ('missing', '  Apps frozen: 1\n', '  Apps frozen: 1\ninvalid\n'):
            with self.assertRaises(vm.ExperimentFailure):
                vm.ams_frozen(invalid,42)

    def test_physical_or_remote_target_rejected(self):
        for serial in ('01234567', 'device', '192.168.1.1:5555', 'emulator-5554;id', ''):
            with self.assertRaises(vm.ExperimentFailure):
                vm.validate_serial(serial)
        self.assertEqual(vm.validate_serial('emulator-5554'), 'emulator-5554')

    def test_only_fixture_named_ams_commands(self):
        calls=[]
        def fake(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout='accepted',stderr='')
        adb=vm.Adb('adb','emulator-5554',run=fake)
        adb.freeze();adb.thaw()
        self.assertEqual(calls,[['adb','-s','emulator-5554','shell','am','freeze','org.guizang.fixture'],['adb','-s','emulator-5554','shell','am','unfreeze','org.guizang.fixture']])

    def test_no_automatic_root_elevation(self):
        calls=[]
        def fake(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout='1' if 'getprop' in args else '2000',stderr='')
        with self.assertRaises(vm.ExperimentFailure):
            vm.Adb('adb','emulator-5554',run=fake).validate_vm()
        self.assertFalse(any('root' in args for args in calls))

    def test_instance_change_or_missing_values_fail(self):
        identity=dict(nonce='x',pid=42,uid=10123,starttime='500',counter=1)
        self.assertTrue(vm.same_instance(identity,identity.copy()))
        for key in ('nonce','pid','uid','starttime'):
            self.assertFalse(vm.same_instance(identity,{**identity,key:None}))
            self.assertFalse(vm.same_instance(identity,{**identity,key:'different'}))

    def test_heartbeat_validation_rejects_strings_and_system_uid(self):
        good=dict(nonce='x',pid=42,uid=10123,starttime='500',counter=1)
        self.assertEqual(vm.require_heartbeat(good),good)
        for change in (dict(uid=1000),dict(counter='1'),dict(starttime='0'),dict(pid=1)):
            with self.assertRaises(vm.ExperimentFailure):
                vm.require_heartbeat({**good,**change})

    def test_adb_failure_keeps_diagnostic_and_command_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence=Path(directory)/'commands.jsonl'
            fake=lambda *a,**k: SimpleNamespace(returncode=1,stdout='',stderr='error: closed')
            with self.assertRaises(vm.AdbFailure):
                vm.Adb('adb','emulator-5554',run=fake,evidence=evidence).command('root')
            row=json.loads(evidence.read_text())
            self.assertEqual(row['stderr'],'error: closed')
            self.assertEqual(row['args'],['root'])
            self.assertIn('finished_at',row)

    def test_root_single_closed_request_reconnects_and_verifies(self):
        adb=Mock()
        adb.command.side_effect=[vm.AdbFailure(['root'],'','adb: error: closed'),'']
        self.assertIn('verified',runner.enable_debug_root(adb))
        self.assertEqual(adb.command.call_args_list[1].args,('wait-for-device',))
        adb.validate_vm.assert_called_once()
        self.assertEqual(sum(call.args==('root',) for call in adb.command.call_args_list),1)

    def test_root_denial_never_retries_or_waits(self):
        for message in ('error: unauthorized','permission denied','error: closed\nunauthorized','adb: unable to connect for root: closed\npermission denied'):
            adb=Mock()
            adb.command.side_effect=vm.AdbFailure(['root'],'',message)
            with self.assertRaises(vm.ExperimentFailure):
                runner.enable_debug_root(adb)
            self.assertEqual(adb.command.call_count,1)
            adb.validate_vm.assert_not_called()

    def test_root_reconnect_requires_uid_validation(self):
        adb=Mock()
        adb.command.return_value='restarting adbd as root'
        adb.validate_vm.side_effect=vm.ExperimentFailure('uid is 2000')
        with self.assertRaises(vm.ExperimentFailure):
            runner.enable_debug_root(adb)

    def test_receipt_reuse_no_reinstallation_and_hash_match(self):
        with tempfile.TemporaryDirectory() as directory:
            apk=Path(directory)/'fixture.apk';apk.write_bytes(b'our own fixture')
            receipt=Path(directory)/'receipt.json'
            expected=dict(schema=1,package=vm.PACKAGE,serial='emulator-5554',boot_id='boot',apk_sha256=vm.sha256(apk),installed_by_experiment=True)
            receipt.write_text(json.dumps(expected))
            adb=Mock(serial='emulator-5554');adb.shell.return_value='package:'+vm.PACKAGE
            with patch.object(vm,'installed_apk_hash',return_value=vm.sha256(apk)):
                self.assertTrue(vm.prepare_fixture(adb,apk,'boot',receipt,True)['reused_without_reinstall'])
            adb.command.assert_not_called()
            with patch.object(vm,'installed_apk_hash',return_value='mismatch'):
                with self.assertRaises(vm.ExperimentFailure):vm.prepare_fixture(adb,apk,'boot',receipt,True)
            with self.assertRaises(vm.ExperimentFailure):vm.prepare_fixture(adb,apk,'other-boot',receipt,True)

    def test_preexisting_fixture_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            apk=Path(directory)/'fixture.apk';apk.write_bytes(b'x')
            adb=Mock(serial='emulator-5554');adb.shell.return_value='package:'+vm.PACKAGE
            with self.assertRaises(vm.ExperimentFailure):vm.prepare_fixture(adb,apk,'boot')
            adb.command.assert_not_called()

    def test_diagnostic_requires_positive_transition_and_clean_exit_history(self):
        good='ActivityManager: freezing 42 org.guizang.fixture\nActivityManager: sync unfroze 42 org.guizang.fixture for shell'
        self.assertTrue(vm.diagnostic_review(vm.EXIT_HEADER,vm.EXIT_HEADER,'',good,42)['no_recorded_fixture_exit'])
        for after,logs in [('',good),(vm.EXIT_HEADER+'\nHistorical Process Exit',good),(vm.EXIT_HEADER,''),(vm.EXIT_HEADER,good+'\nUnable to freeze 42 org.guizang.fixture')]:
            with self.assertRaises(vm.ExperimentFailure):vm.diagnostic_review(vm.EXIT_HEADER,after,'',logs,42)

    def test_cleanup_requires_reap_and_unchanged_kvm(self):
        with tempfile.TemporaryDirectory() as directory:
            absent=Path(directory)/'gone'
            good=dict(emulator_started=True,emulator_reaped=True,owned_home_removed=True)
            runner.verify_cleanup(good,{'mode':432},{'mode':432},absent)
            for report,before,after in [(dict(good,emulator_reaped=False),{},{}),(good,{'mode':432},{'mode':438})]:
                with self.assertRaises(vm.ExperimentFailure):runner.verify_cleanup(report,before,after,absent)

    def test_cleanup_ownership_marker_is_required(self):
        with tempfile.TemporaryDirectory(prefix='guizang-avd-') as directory:
            path=Path(directory).resolve()
            (path/'.guizang-owner.json').write_text(json.dumps(dict(owner='guizang-vm-runner',token='right')))
            with self.assertRaises(vm.ExperimentFailure):runner.remove_owned_home(path,'wrong')
            self.assertTrue(path.is_dir())

    def test_emulator_term_then_kill_reaps_only_owned_child(self):
        import subprocess
        child=Mock();child.poll.return_value=None;child.returncode=-9
        child.wait.side_effect=[subprocess.TimeoutExpired('emulator',20),-9]
        self.assertEqual(runner.terminate_and_reap(child),-9)
        child.terminate.assert_called_once();child.kill.assert_called_once()
        self.assertEqual([call.kwargs['timeout'] for call in child.wait.call_args_list],[20,10])

    def test_avd_identity_empty_console_requires_exact_boot_property(self):
        for console in ('', runner.AVD_NAME, runner.AVD_NAME + '\nOK'):
            adb = Mock(); adb.command.return_value = console
            adb.shell.return_value = runner.AVD_NAME
            self.assertEqual(runner.verify_avd_identity(adb)['boot_property'], runner.AVD_NAME)
            adb.shell.assert_called_once_with('getprop', 'ro.boot.qemu.avd_name')

    def test_avd_identity_missing_or_conflicting_evidence_stops(self):
        for console, prop in [('', ''), ('', 'other'), ('other', runner.AVD_NAME),
                              ('KO: denied', runner.AVD_NAME), ('OK', runner.AVD_NAME),
                              (runner.AVD_NAME, 'other'), (runner.AVD_NAME + '\nextra', runner.AVD_NAME)]:
            adb = Mock(); adb.command.return_value = console; adb.shell.return_value = prop
            with self.assertRaises(vm.ExperimentFailure): runner.verify_avd_identity(adb)
            self.assertFalse(any(call.args == ('root',) for call in adb.command.call_args_list))

    def test_avd_console_error_does_not_fallback_or_request_root(self):
        import subprocess
        for error in (vm.AdbFailure(['emu', 'avd', 'name'], '', 'permission denied'),
                      subprocess.TimeoutExpired('adb emu avd name', 15)):
            adb = Mock(); adb.command.side_effect = error
            with self.assertRaises(type(error)):
                runner.verify_avd_identity(adb)
            adb.shell.assert_not_called()
            self.assertEqual(adb.command.call_args_list[0].args, ('emu', 'avd', 'name'))
            self.assertEqual(adb.command.call_count, 1)

    def test_root_transport_closed_reconnects_without_second_root(self):
        adb = Mock()
        adb.command.side_effect = [vm.AdbFailure(['root'], '', 'adb: unable to connect for root: closed'), '']
        runner.enable_debug_root(adb)
        self.assertEqual([call.args for call in adb.command.call_args_list], [('root',), ('wait-for-device',)])
        adb.validate_vm.assert_called_once()
