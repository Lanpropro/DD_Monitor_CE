"""Offline release-file migration, preservation, recovery and packaging checks."""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm import legacy_cleanup as cleanup, update_install
from ddm.version import VERSION
from dev.build_program_inventory import legacy_catalog, write_inventory
from dev.build_setup import payload_files


def variant(data):
    return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class LegacyCleanupTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'work' / 'legacy-cleanup-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        assert self.root.is_relative_to(base.resolve())
        self.install = self.root / 'install'
        self.install.mkdir()
        self.put('DD监控室CE.exe', b'new-program')
        self.put('_internal/libmpv-2.dll', b'new-runtime')
        self.put('_internal/shared.dll', b'shared')
        self.put('ffmpeg.exe', b'ffmpeg')
        self.put('DDMonitorDiagnostics.exe', b'diagnostics')
        self.put('诊断工具说明.md', b'diagnostics-guide')
        self.put('ddm-build.json', json.dumps({'version': VERSION, 'platform': 'windows-x64',
                                             'update_protocol': 1}).encode())
        write_inventory(self.install)
        self.catalog = self.root / 'catalog.json'
        self.catalog.write_text(json.dumps({'schema': 1, 'files': {
            '_internal/old.dll': [variant(b'old-one'), variant(b'old-two')],
            '_internal/shared.dll': [variant(b'shared')],
            '_internal/modified.dll': [variant(b'old-one')]}}), encoding='utf-8')

    def put(self, name, data):
        path = self.install / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_cleanup(self):
        return cleanup.cleanup_legacy(self.install, self.catalog, VERSION)

    def test_manifestless_mixed_release_files_move_to_recoverable_backup(self):
        old = self.put('_internal/old.dll', b'old-two')
        keep = {'_internal/shared.dll': b'shared', '_internal/custom.dll': b'unknown',
                '_internal/modified.dll': b'changed', 'utils/config.json': b'profile',
                'plugins_user/custom/token.bin': b'plugin', 'recordings/test.mp4': b'recording',
                'cache/custom.txt': b'cache', 'logs/custom.txt': b'log'}
        for name, data in keep.items():
            self.put(name, data)
        self.assertFalse((self.install / update_install.MANIFEST).exists())
        result = self.run_cleanup()
        self.assertEqual(result['moved'], ['_internal/old.dll'])
        self.assertFalse(old.exists())
        backup = Path(result['backup'])
        self.assertTrue(backup.resolve().is_relative_to(self.install.resolve()))
        self.assertEqual((backup / 'files/_internal/old.dll').read_bytes(), b'old-two')
        self.assertEqual(json.loads((backup / 'cleanup-report.json').read_text())['moved'], result['moved'])
        for name, data in keep.items():
            self.assertEqual((self.install / name).read_bytes(), data)
        self.assertEqual(self.run_cleanup()['moved'], [], 'Migration must be idempotent')
        self.assertTrue(backup.exists(), 'Recovery copies must not be purged on the next start')

    def test_old_updater_leaves_unknown_files_then_new_start_cleans_them(self):
        source = self.install
        archive = self.root / 'new.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            for path in source.rglob('*'):
                if path.is_file():
                    package.write(path, 'DD监控室CE/' + path.relative_to(source).as_posix())
        old_root = self.root / 'old-install'
        old_root.mkdir()
        old_exe = old_root / 'DD监控室CE.exe'
        old_exe.write_bytes(b'old-program')
        old_file = old_root / '_internal/old.dll'
        old_file.parent.mkdir()
        old_file.write_bytes(b'old-one')
        plan = update_install.prepare(archive, old_root, old_exe, expected_version=VERSION)
        try:
            update_install.apply_plan(plan)
            self.assertTrue(old_file.exists(), 'Existing updater cannot infer old unregistered files')
            result = cleanup.cleanup_legacy(old_root, self.catalog, VERSION)
            self.assertEqual(result['moved'], ['_internal/old.dll'])
            self.assertFalse(old_file.exists())
            self.assertTrue((old_root / update_install.MANIFEST).exists())
        finally:
            update_install.discard_plan(plan, old_root)

    def test_current_paths_are_protected_even_with_case_alias_and_old_hash(self):
        inventory = json.loads((self.install / cleanup.INVENTORY).read_text())
        inventory['files'] = [name.upper() if name.endswith('shared.dll') else name
                              for name in inventory['files']]
        (self.install / cleanup.INVENTORY).write_text(json.dumps(inventory), encoding='utf-8')
        self.assertEqual(self.run_cleanup()['moved'], [])
        self.assertEqual((self.install / '_internal/shared.dll').read_bytes(), b'shared')

    def test_invalid_or_wrong_version_metadata_does_not_clean_anything(self):
        old = self.put('_internal/old.dll', b'old-one')
        path = self.install / cleanup.INVENTORY
        original = path.read_bytes()
        for value in ({'schema': 1, 'version': 'wrong', 'files': []}, {'schema': 1, 'files': []}):
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                self.run_cleanup()
            self.assertTrue(old.exists())
        path.write_bytes(original)
        data = json.loads(self.catalog.read_text())
        data['files']['utils/config.json'] = [variant(b'profile')]
        self.catalog.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.run_cleanup()
        self.assertTrue(old.exists(), 'Validate the entire catalog before moving any file')

    def test_locked_file_stays_and_is_retried(self):
        old = self.put('_internal/old.dll', b'old-one')
        rename = Path.rename
        def locked(path, target):
            if path == old:
                raise PermissionError('synthetic file lock')
            return rename(path, target)
        with patch.object(Path, 'rename', locked):
            result = self.run_cleanup()
        self.assertTrue(old.exists())
        self.assertIn('_internal/old.dll', result['skipped'])
        self.assertEqual(self.run_cleanup()['moved'], ['_internal/old.dll'])

    def test_file_changed_during_inspection_is_restored(self):
        old = self.put('_internal/old.dll', b'old-one')
        rename = Path.rename
        def changed(path, target):
            if path == old:
                old.write_bytes(b'user change')
            return rename(path, target)
        with patch.object(Path, 'rename', changed):
            result = self.run_cleanup()
        self.assertEqual(old.read_bytes(), b'user change')
        self.assertEqual(result['moved'], [])

    def test_verification_io_failure_restores_the_original_file(self):
        old = self.put('_internal/old.dll', b'old-one')
        digest = hashlib.file_digest
        count = 0
        def fail_second_read(source, algorithm):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('synthetic backup read failure')
            return digest(source, algorithm)
        with patch.object(hashlib, 'file_digest', fail_second_read):
            result = self.run_cleanup()
        self.assertEqual(old.read_bytes(), b'old-one')
        self.assertEqual(result['moved'], [])
        self.assertIn('_internal/old.dll', result['skipped'])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction protection')
    def test_program_and_backup_junctions_never_touch_other_directories(self):
        original_install = self.install
        for index, link_name in enumerate(('_internal/linked', 'work')):
            self.install = self.root / f'junction-case-{index}'
            shutil.copytree(original_install, self.install)
            external = self.root / ('external-' + link_name.replace('/', '-'))
            external.mkdir()
            victim = external / 'old.dll'
            victim.write_bytes(b'old-one')
            link = self.install / link_name
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(external)],
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(link.absolute().is_relative_to(self.install))
            self.assertTrue(link.is_junction())
            try:
                catalog = json.loads(self.catalog.read_text())
                catalog['files']['_internal/linked/old.dll'] = [variant(b'old-one')]
                self.catalog.write_text(json.dumps(catalog))
                self.put('_internal/old.dll', b'old-one')
                self.run_cleanup()
                self.assertEqual(victim.read_bytes(), b'old-one')
                if link_name == 'work':
                    self.assertTrue((self.install / '_internal/old.dll').exists())
            finally:
                os.rmdir(link)  # Remove only this verified fixture junction, never its target.

    def test_source_mode_does_nothing_and_frozen_work_is_background(self):
        with patch.object(sys, 'frozen', False, create=True), patch.object(cleanup, 'cleanup_legacy') as clean:
            self.assertIsNone(cleanup.start_legacy_cleanup(self.install))
            clean.assert_not_called()
        entered, release = threading.Event(), threading.Event()
        def slow(root):
            entered.set()
            self.assertTrue(release.wait(3))
            return {'moved': [], 'skipped': [], 'backup': None}
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, 'executable', str(self.install / 'DD监控室CE.exe')), \
                patch.object(cleanup, 'cleanup_legacy', side_effect=slow):
            start = time.perf_counter()
            worker = cleanup.start_legacy_cleanup(self.install)
            self.assertLess(time.perf_counter() - start, .2)
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(worker.is_alive())
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())

    def test_generated_inventory_is_deterministic_and_allowed_by_setup(self):
        first = (self.install / cleanup.INVENTORY).read_bytes()
        self.put('utils/config.json', b'not a program file')
        write_inventory(self.install)
        self.assertEqual((self.install / cleanup.INVENTORY).read_bytes(), first)
        (self.install / 'utils/config.json').unlink()
        self.assertIn(cleanup.INVENTORY, payload_files(self.install))

    def test_catalog_hashes_contents_and_excludes_user_data(self):
        archive = self.root / 'DD监控室CE-v0.1-exe.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('program/_internal/old.dll', b'old-one')
            package.writestr('program/utils/config.json', b'account not read')
        catalog = legacy_catalog([archive])
        self.assertEqual(catalog['files'], {'_internal/old.dll': [variant(b'old-one')]})
        self.assertEqual(catalog['releases'][0]['program_files'], 1)
        with zipfile.ZipFile(archive, 'a') as package:
            package.writestr('program/../escape.dll', b'bad')
        with self.assertRaises(ValueError):
            legacy_catalog([archive])

    def test_recovery_report_cannot_overwrite_an_archived_program_file(self):
        self.put('cleanup-report.json', b'historical file')
        catalog = json.loads(self.catalog.read_text())
        catalog['files']['cleanup-report.json'] = [variant(b'historical file')]
        self.catalog.write_text(json.dumps(catalog))
        result = self.run_cleanup()
        saved = Path(result['backup']) / 'files/cleanup-report.json'
        self.assertEqual(saved.read_bytes(), b'historical file')

    def test_bundled_catalog_covers_all_six_archived_releases(self):
        catalog = json.loads(cleanup.CATALOG.read_text(encoding='utf-8'))
        self.assertEqual(catalog['schema'], 1)
        self.assertEqual({item['version'] for item in catalog['releases']},
                         {'0.1', '0.2', '0.3', '0.3.1', '0.4', '0.5'})
        self.assertIn('_internal/libvlc.dll', catalog['files'])
        for name, variants in catalog['files'].items():
            update_install.relative_path(name)
            self.assertTrue(variants)
            for item in variants:
                self.assertEqual(len(item['sha256']), 64)


if __name__ == '__main__':
    unittest.main()
