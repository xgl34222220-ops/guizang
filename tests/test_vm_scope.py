import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
spec = importlib.util.spec_from_file_location('vm_validate', Path(__file__).parents[1] / 'tools/vm_validate.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


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
            return SimpleNamespace(returncode=0,stdout='accepted')
        adb=vm.Adb('adb','emulator-5554',run=fake)
        adb.freeze();adb.thaw()
        self.assertEqual(calls,[['adb','-s','emulator-5554','shell','am','freeze','org.guizang.fixture'],['adb','-s','emulator-5554','shell','am','unfreeze','org.guizang.fixture']])

    def test_no_automatic_root_elevation(self):
        calls=[]
        def fake(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout='1' if 'getprop' in args else '2000')
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
