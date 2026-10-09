"""Regression tests for the hark/optimize-pr1 hardening pass (host-only)."""
from dataclasses import replace
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

from core.boot_guard import BootGuard
from core.lifecycle import Freezer
from core.performance import Transaction, scene
from test_safety import APP, SAFE, CAPS, CONFIG, Backend, MemoryJournal, MemoryStore

ROOT = Path(__file__).resolve().parent.parent


class IdentityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.engine = Freezer(self.backend, CONFIG, CAPS)

    def test_non_ascii_or_malformed_package_segments_rejected(self):
        for package in ('org.例子.reader', 'org.example.²', 'org.1example', 'org..reader',
                        'org.example.reader\n', 'org.exa-mple', 'reader', '.org.reader',
                        'org.' + 'a' * 300):
            with self.subTest(package=package):
                self.assertFalse(replace(APP, package=package).valid())

    def test_valid_android_packages_still_accepted(self):
        for package in ('org.example.reader', 'com.a_b.C9', 'a.b'):
            self.assertTrue(replace(APP, package=package).valid())

    def test_non_integer_identity_fields_rejected(self):
        for change in ({'uid': 10123.0}, {'uid': True}, {'pid': '234'}, {'starttime': None},
                       {'boot_id': None}, {'package': None}):
            with self.subTest(change=change):
                self.assertFalse(replace(APP, **change).valid())

    def test_garbled_background_duration_never_freezes(self):
        for value in (None, '20000', 20000.0, True, -1):
            with self.subTest(value=value):
                self.assertEqual(self.engine.consider(APP, SAFE, value), 'invalid_signal')
        self.assertEqual(self.backend.calls, [])


class SceneHardeningTests(unittest.TestCase):
    def test_non_boolean_signals_are_unknown(self):
        base = dict(screen_on=True, interactive=True, audio=False, thermal='normal')
        for key in ('screen_on', 'interactive', 'audio'):
            for value in ('false', 'true', 0, 1):
                with self.subTest(key=key, value=value):
                    self.assertEqual(scene(**{**base, key: value}), 'unknown')
        self.assertEqual(scene(**{**base, 'thermal': 'HOT'}), 'unknown')
        self.assertEqual(scene(**{**base, 'interactive': False}), 'balanced')


class CountingJournal(MemoryJournal):
    def __init__(self):
        super().__init__()
        self.saves = 0

    def save(self, entries):
        self.saves += 1
        super().save(entries)


class JournalChurnTests(unittest.TestCase):
    def test_restore_without_progress_does_not_rewrite_journal(self):
        journal = CountingJournal()
        store = MemoryStore(journal)
        tx = Transaction(store, journal, {'test.cpu': frozenset({'90'})})
        self.assertTrue(tx.restore())
        self.assertEqual(journal.saves, 0)
        self.assertEqual(tx.apply({'test.cpu': '90'}, enabled=True, dry_run=False), 'applied')
        store.values['test.cpu'] = '80'  # another actor owns it now
        saves = journal.saves
        self.assertFalse(tx.restore())
        self.assertFalse(tx.restore())
        self.assertEqual(journal.saves, saves)
        store.values['test.cpu'] = '90'
        self.assertTrue(tx.restore())
        self.assertEqual(journal.entries, [])


class BootGuardHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'guard'
        self.guard = BootGuard(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_crash_leftover_temporaries_do_not_accumulate(self):
        for index in range(5):
            (self.path / f'.state-crash{index}').write_text('{')
        outside = Path(self.temp.name) / 'outside'
        outside.write_text('keep')
        (self.path / '.state-link').symlink_to(outside)
        self.guard.begin('a')
        self.assertEqual({p.name for p in self.path.iterdir()}, {'lock', 'state.json'})
        self.assertEqual(outside.read_text(), 'keep')
        for boot in 'bcdefgh':
            self.guard.begin(boot)
        self.assertEqual({p.name for p in self.path.iterdir()}, {'lock', 'state.json'})

    def test_symlinked_state_directory_refused(self):
        real = Path(self.temp.name) / 'elsewhere'
        real.mkdir()
        link = Path(self.temp.name) / 'linked'
        link.symlink_to(real)
        with self.assertRaises(OSError):
            BootGuard(link)
        self.assertEqual(list(real.iterdir()), [])

    def test_lock_descriptor_not_inherited(self):
        with self.guard.lock():
            fds = [int(n) for n in os.listdir('/proc/self/fd')] if os.path.isdir('/proc/self/fd') else []
            for fd in fds:
                try:
                    if os.readlink(f'/proc/self/fd/{fd}').endswith('/guard/lock'):
                        self.assertFalse(os.get_inheritable(fd))
                except OSError:
                    pass

    def test_snapshot_is_read_only(self):
        self.assertEqual(self.guard.snapshot()['disabled'], False)
        self.assertFalse((self.path / 'state.json').exists())
        (self.path / 'state.json').write_text('{bad')
        self.assertTrue(self.guard.snapshot()['disabled'])
        self.assertEqual((self.path / 'state.json').read_text(), '{bad')

    def test_disabled_guard_only_re_enabled_by_explicit_reset(self):
        for boot in 'abc':
            self.guard.begin(boot)
            self.guard.finish(boot, healthy=False)
        self.assertTrue(self.guard.begin('d')['disabled'])
        for value in (None, 'true', 1):
            with self.assertRaises(ValueError):
                self.guard.reset(acknowledged=value)
        self.assertTrue(self.guard.snapshot()['disabled'])
        state = self.guard.reset(acknowledged=True)
        self.assertEqual((state['disabled'], state['failures']), (False, 0))
        self.assertEqual(self.guard.begin('e')['status'], 'pending')


class ModuleScriptInvariantTests(unittest.TestCase):
    """Static boot-safety invariants for everything shipped in module/."""
    SCRIPTS = sorted((ROOT / 'module').glob('*.sh'))

    def test_no_early_boot_or_sepolicy_hooks(self):
        for name in ('post-fs-data.sh', 'post-mount.sh', 'boot-completed.sh', 'sepolicy.rule',
                     'system.prop'):
            self.assertFalse((ROOT / 'module' / name).exists(), name)

    def test_scripts_make_no_device_writes_or_waits(self):
        forbidden = re.compile(
            r'resetprop|setprop|\bsettings\s+put|\bpm\s+(disable|suspend|hide)|\bam\s+(force-stop|kill)'
            r'|>\s*/(sys|proc|data|dev/(?!null\b))|\brm\s+-|\bdd\s|\bsleep\b|while\s+true|\bmkdir\b|\btouch\b'
            r'|\bchmod\b|\bchown\b|\bmount\b')
        for script in self.SCRIPTS:
            code = '\n'.join(line for line in script.read_text().splitlines()
                             if not line.lstrip().startswith('#'))
            with self.subTest(script=script.name):
                self.assertIsNone(forbidden.search(code))

    def test_service_honours_disable_flag_before_anything_else(self):
        lines = [line for line in (ROOT / 'module/service.sh').read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        self.assertTrue(lines[0].startswith('MODDIR='))
        self.assertIn('/disable', lines[1])
        self.assertIn('exit 0', lines[1])


class ProbeScriptTests(unittest.TestCase):
    def run_probe(self, getprop_body):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / 'getprop'
            fake.write_text('#!/bin/sh\n' + getprop_body)
            fake.chmod(0o755)
            env = {**os.environ, 'PATH': temp + os.pathsep + os.environ.get('PATH', '')}
            out = subprocess.run(['sh', str(ROOT / 'module/probe.sh')], env=env, check=True,
                                 capture_output=True, text=True, timeout=10).stdout
        return out

    def test_empty_and_multiline_properties_stay_single_line(self):
        out = self.run_probe('case "$1" in ro.build.version.sdk) echo 35;; '
                             "ro.product.model) printf 'Pixel\\nX\\n';; *) echo;; esac\n")
        lines = out.splitlines()
        self.assertTrue(all(line.count('=') == 1 for line in lines), out)
        values = dict(line.split('=') for line in lines)
        self.assertEqual((values['android_sdk'], values['model'], values['soc']),
                         ('35', 'Pixel X', 'unknown'))
        self.assertEqual(values['freezing'], 'disabled')
        self.assertEqual(values['performance_writes'], 'disabled')


if __name__ == '__main__':
    unittest.main()
