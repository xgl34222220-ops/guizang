from dataclasses import replace, fields
from pathlib import Path
import json
import tempfile
import unittest
from core.lifecycle import Identity, Protection, Capabilities, Config, Freezer, Phase
from core.performance import Change, Transaction, scene
from core.boot_guard import BootGuard

APP = Identity('org.example.reader', 10123, 234, 54321, 'boot-a')
SAFE = Protection(**{f.name: False for f in fields(Protection)})
CAPS = Capabilities(True, True, True, True)
CONFIG = Config(True, False, frozenset({APP.package}))


class Backend:
    def __init__(self):
        self.current = APP
        self.frozen = False
        self.calls = []
        self.freeze_result = True
        self.thaw_result = True
        self.raise_freeze = False
        self.raise_read = False

    def identity(self, pid):
        if self.raise_read:
            raise OSError('lost proc access')
        return self.current

    def freeze(self, identity):
        assert identity == self.current
        self.calls.append('freeze')
        self.frozen = True
        if self.raise_freeze:
            raise OSError('failure after mutation')
        return self.freeze_result

    def thaw(self, identity):
        assert identity == self.current
        self.calls.append('thaw')
        if self.thaw_result:
            self.frozen = False
        return self.thaw_result

    def is_frozen(self, identity):
        return self.frozen


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.engine = Freezer(self.backend, CONFIG, CAPS)

    def consider(self, **kwargs):
        return self.engine.consider(kwargs.get('identity', APP), kwargs.get('protection', SAFE),
                                    kwargs.get('background_ms', 12000))

    def test_default_disabled(self):
        engine = Freezer(self.backend)
        self.assertEqual(engine.consider(APP, SAFE, 20000), 'disabled')
        self.assertEqual(self.backend.calls, [])

    def test_dry_run_has_no_mutations(self):
        self.engine.config = replace(CONFIG, dry_run=True)
        self.assertEqual(self.consider(), 'would_freeze')
        self.assertEqual(self.engine.owned, set())
        self.assertEqual(self.backend.calls, [])

    def test_every_protection_and_unknown_denies(self):
        for f in fields(Protection):
            for value in (True, None, 'false', 0):
                with self.subTest(protection=f.name, value=value):
                    reason = self.consider(protection=replace(SAFE, **{f.name: value}))
                    self.assertTrue(reason.startswith(('protected:', 'unknown:')))
        self.assertFalse(self.backend.calls)

    def test_each_capability_missing_denies(self):
        for f in fields(Capabilities):
            self.engine.capabilities = replace(CAPS, **{f.name: False})
            self.assertEqual(self.consider(), 'capability_unverified')
        self.assertFalse(self.backend.calls)

    def test_non_allowlisted(self):
        self.engine.config = replace(CONFIG, allowlist=frozenset())
        self.assertEqual(self.consider(), 'not_allowlisted')

    def test_grace_minimum(self):
        self.engine.config = replace(CONFIG, grace_ms=0)
        self.assertEqual(self.consider(background_ms=9999), 'grace_period')
        self.assertEqual(self.consider(background_ms=10000), 'frozen')

    def test_invalid_uid_ranges_and_pid(self):
        for uid in (0, 9999, 20000, 99001, 110123):
            self.assertEqual(self.consider(identity=replace(APP, uid=uid)), 'invalid_identity')
        self.assertEqual(self.consider(identity=replace(APP, pid=1)), 'invalid_identity')
        self.assertEqual(self.consider(identity=replace(APP, starttime=0)), 'invalid_identity')

    def test_identity_pid_uid_starttime_boot_and_package(self):
        for attr, val in [('uid', 10124), ('starttime', 54322), ('boot_id', 'boot-b'),
                          ('package', 'org.example.new')]:
            self.backend.current = replace(APP, **{attr: val})
            self.assertEqual(self.consider(), 'identity_changed')
        self.assertFalse(self.backend.calls)

    def test_existing_external_freeze_not_owned(self):
        self.backend.frozen = True
        self.assertEqual(self.consider(), 'externally_frozen')
        self.engine.stop()
        self.assertFalse(self.backend.calls)
        self.assertTrue(self.backend.frozen)

    def test_freeze_thaw_and_repeated_requests(self):
        self.assertEqual(self.consider(), 'frozen')
        self.assertEqual(self.consider(), 'already_owned')
        self.assertEqual(self.engine.stop(), 'thawed')
        self.assertEqual(self.engine.stop(), 'thawed')
        self.assertEqual(self.backend.calls, ['freeze', 'thaw'])
        self.assertFalse(self.engine.owned)

    def test_thaw_failure_retains_ownership_and_blocks(self):
        self.consider()
        self.backend.thaw_result = False
        self.assertEqual(self.engine.thaw_all(), 'thaw_failed')
        self.assertEqual(self.engine.owned, {APP})
        self.assertEqual(self.consider(), 'degraded')
        self.backend.thaw_result = True
        self.assertEqual(self.engine.thaw_all(), 'thawed')
        self.assertEqual(self.consider(), 'degraded')

    def test_partial_freeze_failure_compensates(self):
        for raised in (False, True):
            with self.subTest(exception=raised):
                self.setUp()
                self.backend.freeze_result = False
                self.backend.raise_freeze = raised
                self.assertEqual(self.consider(), 'freeze_failed')
                self.assertEqual(self.backend.calls, ['freeze', 'thaw'])
                self.assertFalse(self.backend.frozen)
                self.assertEqual(self.consider(), 'degraded')

    def test_reused_pid_never_thawed(self):
        self.consider()
        self.backend.current = replace(APP, starttime=99999)
        self.assertEqual(self.engine.thaw_all(), 'thawed')
        self.assertEqual(self.backend.calls, ['freeze'])

    def test_foreground_or_unknown_signal_thaws(self):
        for signal in (replace(SAFE, foreground=True), Protection()):
            self.setUp()
            self.consider()
            self.assertEqual(self.engine.safety_signal(APP, signal), 'thawed')
            self.assertFalse(self.backend.frozen)

    def test_missing_frozen_state_never_authorizes_freeze(self):
        self.backend.frozen = None
        self.assertEqual(self.consider(), 'observation_failed')
        self.assertFalse(self.backend.calls)

    def test_protection_recheck_thaws_owned_process(self):
        self.consider()
        self.assertEqual(self.consider(protection=replace(SAFE, foreground=True)), 'protected:foreground')
        self.assertFalse(self.backend.frozen)

    def test_configuration_disable_thaws_owned_process(self):
        self.consider()
        self.engine.config = Config()
        self.assertEqual(self.consider(), 'disabled')
        self.assertFalse(self.backend.frozen)

    def test_string_boolean_never_enables_live_writes(self):
        self.engine.config = replace(CONFIG, enabled='true')
        self.assertEqual(self.consider(), 'disabled')
        self.engine.config = replace(CONFIG, dry_run='false')
        self.assertEqual(self.consider(), 'would_freeze')
        self.assertFalse(self.backend.calls)

    def test_observation_error_blocks_without_freezing(self):
        self.backend.raise_read = True
        self.assertEqual(self.consider(), 'observation_failed')
        self.assertEqual(self.consider(), 'degraded')
        self.assertFalse(self.backend.calls)


class MemoryJournal:
    def __init__(self):
        self.entries = []
        self.fail = False
    def load(self):
        return self.entries.copy()
    def save(self, entries):
        if self.fail:
            raise OSError('disk full')
        self.entries = entries.copy()


class MemoryStore:
    def __init__(self, journal):
        self.values = {'test.cpu': '100', 'test.gpu': '200'}
        self.calls = []
        self.journal = journal
        self.fail_key = None
        self.partial = False
    def read(self, key):
        return self.values[key]
    def write(self, key, value):
        assert self.journal.entries, 'write before durable intent'
        self.calls.append((key, value))
        if self.partial:
            self.values[key] = value
            self.partial = False
            raise OSError('after write')
        if key == self.fail_key:
            raise OSError('write denied')
        self.values[key] = value


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.journal = MemoryJournal()
        self.store = MemoryStore(self.journal)
        self.tx = Transaction(self.store, self.journal, {'test.cpu': frozenset({'100', '90'}),
                                                       'test.gpu': frozenset({'200', '180'})})

    def apply(self, desired=None, **kwargs):
        return self.tx.apply(desired or {'test.cpu': '90', 'test.gpu': '180'},
                             enabled=True, dry_run=False, **kwargs)

    def test_observe_default_and_unsupported_key_value(self):
        self.assertEqual(self.tx.apply({'test.cpu': '90'}), 'observe_only')
        self.assertEqual(self.apply({'/sys/danger': '1'}), 'unsupported')
        self.assertEqual(self.apply({'test.cpu': '999999'}), 'unsupported')
        self.assertFalse(self.store.calls)

    def test_wal_before_write_and_restore_idempotent(self):
        self.assertEqual(self.apply(), 'applied')
        self.assertTrue(self.journal.entries)
        self.assertTrue(self.tx.restore())
        self.assertEqual(self.store.values, {'test.cpu': '100', 'test.gpu': '200'})
        calls = self.store.calls.copy()
        self.assertTrue(self.tx.restore())
        self.assertEqual(self.store.calls, calls)

    def test_pending_wal_blocks_new_writes(self):
        self.apply()
        calls = self.store.calls.copy()
        self.assertEqual(self.apply(), 'pending_recovery')
        self.assertEqual(self.store.calls, calls)

    def test_partial_failure_reverse_rollback(self):
        self.store.fail_key = 'test.gpu'
        self.assertEqual(self.apply(), 'rolled_back')
        self.assertEqual(self.store.values['test.cpu'], '100')
        self.assertFalse(self.journal.entries)

    def test_exception_after_write_restores(self):
        self.store.partial = True
        self.assertEqual(self.apply(), 'rolled_back')
        self.assertEqual(self.store.values['test.cpu'], '100')

    def test_crash_replay_uses_saved_originals(self):
        self.apply()
        restarted = Transaction(self.store, self.journal, {})
        self.assertTrue(restarted.restore())
        self.assertEqual(self.store.values['test.cpu'], '100')

    def test_other_actor_is_not_overwritten(self):
        self.apply()
        self.store.values['test.cpu'] = '80'
        self.assertFalse(self.tx.restore())
        self.assertEqual(self.store.values['test.cpu'], '80')
        self.assertEqual(len(self.journal.entries), 1)
        self.assertEqual(self.apply(), 'pending_recovery')

    def test_restore_failure_remains_retryable(self):
        self.apply()
        self.store.fail_key = 'test.cpu'
        self.assertFalse(self.tx.restore())
        self.assertEqual(len(self.journal.entries), 1)
        self.store.fail_key = None
        self.assertTrue(self.tx.restore())

    def test_disk_failure_permits_no_writes(self):
        self.journal.fail = True
        with self.assertRaises(OSError):
            self.apply()
        self.assertFalse(self.store.calls)

    def test_scene_thermal_priority_and_unknown(self):
        base = dict(screen_on=True, interactive=True, audio=False, thermal='normal')
        self.assertEqual(scene(**base), 'interactive')
        for key in base:
            self.assertEqual(scene(**{**base, key: None}), 'unknown')
        self.assertEqual(scene(**{**base, 'thermal': 'hot', 'audio': True}), 'thermal_guard')
        self.assertEqual(scene(**{**base, 'audio': True}), 'media')
        self.assertEqual(scene(**{**base, 'screen_on': False}), 'standby')


class BootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.guard = BootGuard(self.path)
    def tearDown(self):
        self.temp.cleanup()

    def test_same_boot_begin_and_finish_are_idempotent(self):
        self.guard.begin('a')
        self.assertEqual(self.guard.begin('a')['failures'], 0)
        self.guard.finish('a', healthy=False)
        self.guard.finish('a', healthy=False)
        self.assertEqual(self.guard.begin('a')['failures'], 1)

    def test_three_failed_attempts_disable_only_itself(self):
        for boot in 'abc':
            self.guard.begin(boot)
            state = self.guard.finish(boot, healthy=False)
        self.assertTrue(state['disabled'])
        self.assertEqual(state['failures'], 3)
        self.assertEqual(self.guard.begin('d'), state)
        self.assertEqual(self.guard.finish('d', healthy=True), state)
        self.assertEqual(set(p.name for p in self.path.iterdir()), {'lock', 'state.json'})

    def test_unfinished_boot_counted_once_next_boot(self):
        self.guard.begin('a')
        self.assertEqual(self.guard.begin('b')['failures'], 1)
        self.assertEqual(self.guard.begin('b')['failures'], 1)
        self.guard.begin('c')
        self.assertTrue(self.guard.begin('d')['disabled'])

    def test_healthy_resets_only_matching_pending_attempt(self):
        self.guard.begin('a')
        self.guard.finish('a', healthy=False)
        self.guard.begin('b')
        self.assertEqual(self.guard.finish('a', healthy=True)['failures'], 1)
        self.assertEqual(self.guard.finish('b', healthy=True)['failures'], 0)

    def test_corruption_disables_no_auto_reset(self):
        for content in ('{bad', '[]', '{}', 'null', '{"schema":1}'):
            (self.path / 'state.json').write_text(content)
            self.assertTrue(self.guard.begin('a')['disabled'])

    def test_symlink_state_rejected(self):
        other = self.path / 'outside'
        other.write_text('{}')
        (self.path / 'state.json').symlink_to(other)
        self.assertTrue(self.guard.begin('a')['disabled'])
        self.assertEqual(other.read_text(), '{}')

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            self.guard.begin('')
        with self.assertRaises(ValueError):
            self.guard.finish('a', healthy='false')
        with self.assertRaises(ValueError):
            BootGuard(self.path, failure_limit=1)

    def test_restart_reads_persisted_attempt(self):
        self.guard.begin('a')
        restarted = BootGuard(self.path)
        self.assertEqual(restarted.begin('b')['failures'], 1)
        self.assertEqual(json.loads((self.path / 'state.json').read_text())['boot'], 'b')


if __name__ == '__main__':
    unittest.main()
