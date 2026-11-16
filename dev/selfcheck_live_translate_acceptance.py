"""Acceptance data and package boundaries; no model, account, or plugin execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from ddm import config, plugins

SPEC = importlib.util.spec_from_file_location('translation_acceptance', Path(__file__).with_name('accept_live_translate.py'))
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


class AcceptanceIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = self.root / 'live_translate-0.1.zip'
        with zipfile.ZipFile(self.package, 'w') as archive:
            archive.writestr('live_translate/plugin.py', "raise AssertionError('installation must not execute code')")
            archive.writestr('live_translate/plugin.json', json.dumps({
                'id': 'live_translate', 'name': 'fixture', 'version': '0.1', 'description': 'fixture'}))
        self.candidate = self.root / 'candidate.json'
        self.candidate.write_text(json.dumps({
            'package': str(self.package), 'sha256': hashlib.sha256(self.package.read_bytes()).hexdigest(),
            'options': {'python': 'fixture/python.exe'}}), encoding='utf-8')
        self.enterContext(patch.object(acceptance, 'ROOT', self.root))
        self.enterContext(patch.object(config, 'DATA_ROOT', None))
        self.enterContext(patch.object(config, 'CONFIG_PATH', 'must-not-read-personal-config.json'))
        self.enterContext(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', 'must-not-read-installed-plugins'))

    def tearDown(self):
        self.doCleanups()
        self.temporary.cleanup()

    def test_profile_and_install_are_separate_and_start_with_no_accounts(self):
        reads = []
        with patch.object(config, '_read_json', side_effect=lambda path: reads.append(path) or {}):
            data, state = acceptance.prepare(self.candidate)
        self.assertTrue(data.is_relative_to(self.root / 'work/live-translate-acceptance'))
        self.assertEqual(state['plugins_enabled'], ['live_translate'])
        self.assertEqual(state['rooms'], [])
        self.assertNotIn('accounts', state)
        self.assertEqual(state['plugins']['live_translate']['options']['python'], 'fixture/python.exe')
        self.assertFalse(reads)
        self.assertTrue((data / 'plugins_user/live_translate/plugin.py').is_file())

    def test_changed_copy_is_refused_and_preserved(self):
        data, _state = acceptance.prepare(self.candidate)
        installed = data / 'plugins_user/live_translate/plugin.py'
        installed.write_text('preserve local changes', encoding='utf-8')
        with self.assertRaises(ValueError):
            acceptance.prepare(self.candidate)
        self.assertEqual(installed.read_text(encoding='utf-8'), 'preserve local changes')

    def test_wrong_package_digest_is_refused_before_install(self):
        self.package.write_bytes(b'changed package')
        with self.assertRaises(ValueError):
            acceptance.prepare(self.candidate)
        self.assertFalse((self.root / 'work').exists())


if __name__ == '__main__':
    unittest.main()
