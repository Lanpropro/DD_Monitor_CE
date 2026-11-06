"""Same-version update ordering, release feeds, package revision and rollback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm import online, update_install
from ddm.update_version import app_tag, installed_revision, release_label, revision, update_identity, update_key
from selfcheck_online import Client, Response, asset


def manifest(number=1, version='0.7.1', tag=None):
    tag = tag or 'v'+version
    return {'version': version, 'revision': number, 'release_tag': tag,
            'asset_name': f'DDMonitorCE-v{version}-exe.zip',
            'url': f'https://github.com/{online.APP_REPOSITORY}/releases/download/{tag}/DDMonitorCE-v{version}-exe.zip',
            'sha256': hashlib.sha256(b'zip').hexdigest(), 'size': 3, 'notes': 'Hotfix notes'}


class HotfixTests(unittest.TestCase):
    def check(self, entry, current='0.7.1', number=0):
        with patch.object(online, 'latest_manifest', return_value=entry), \
                patch.object(online, 'release_notes', return_value='Published notes'):
            return online.app_release(None, current, number)

    def test_revision_orders_within_version_and_normal_upgrade_wins(self):
        self.assertIsNotNone(self.check(manifest(1)))
        self.assertIsNone(self.check(manifest(1), number=1))
        self.assertIsNone(self.check(manifest(1), number=2))
        self.assertIsNotNone(self.check(manifest(2), number=1))
        self.assertIsNotNone(self.check(manifest(0, '0.7.2'), number=99))
        self.assertIsNone(self.check(manifest(99, '0.7.0')))
        entry = manifest(1)
        entry.update(notes='Edited notes', sha256='a'*64)
        self.assertIsNone(self.check(entry, number=1), 'Body or asset edits alone are not a new revision')
        self.assertGreater(update_key('0.7.2'), update_key('0.7.1', 999))

    def test_legacy_metadata_is_revision_zero_and_public_version_is_unchanged(self):
        entry = manifest(0)
        entry.pop('revision')
        self.assertIsNone(self.check(entry))
        offer = self.check(manifest(1))
        self.assertEqual(offer['version'], '0.7.1')
        self.assertEqual(release_label(offer), '0.7.1 热修复')
        self.assertEqual(update_identity(entry), '0.7.1')
        self.assertNotEqual(update_identity(entry), update_identity(offer))
        self.assertNotEqual(update_identity(offer), update_identity(manifest(2)))

    def test_tag_revisions_and_invalid_metadata(self):
        self.assertEqual(app_tag('v0.7.1'), ('0.7.1', 0))
        self.assertEqual(app_tag('v0.7.1-hotfix'), ('0.7.1', 1))
        self.assertEqual(app_tag('v0.7.1-hotfix.10'), ('0.7.1', 10))
        for tag in ('v0.7.1-rc1', 'v0.7.1-hotfix.0', 'v0.7.1-hotfix.x'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                app_tag(tag)
        for value in (-1, True, '1', 1.5, None):
            with self.subTest(revision=value), self.assertRaises(ValueError):
                revision(value)
        with self.assertRaises(ValueError):
            self.check(manifest(2, tag='v0.7.1-hotfix.1'))
        entry = manifest(1, tag='v0.7.1-hotfix.1')
        with patch.object(online, 'latest_manifest', return_value=entry), \
                patch.object(online, 'release_notes', return_value='Hotfix page') as notes:
            self.assertEqual(online.app_release(None, '0.7.1')['notes'], 'Hotfix page')
            notes.assert_called_once_with(None, '0.7.1', 'v0.7.1-hotfix.1')

    def test_api_fallback_recognizes_hotfix_tags_and_excludes_drafts(self):
        package = asset('DDMonitorCE-v0.7.1-exe.zip', repository=online.APP_REPOSITORY)
        published = [{'tag_name': tag, 'assets': [package], **flags} for tag, flags in (
            ('v0.7.1-hotfix.2', {}), ('v0.7.1-hotfix.10', {}), ('v0.7.2', {'prerelease': True}),
            ('v0.8', {'draft': True}), ('v0.7.1-rc1', {}))]
        published.insert(0, {'tag_name': 'v0.7.1-hotfix.1', 'assets': []})
        offer = online.app_release(Client([Response(payload=published)]), '0.7.1', 0)
        self.assertEqual((offer['version'], offer['revision']), ('0.7.1', 10))
        self.assertIsNone(online.app_release(Client([Response(payload=published)]), '0.7.1', 10))

    def test_api_reads_replaced_release_manifest_with_hash_validation(self):
        entry = manifest(2)
        body = json.dumps(entry).encode()
        metadata = asset('app-update.json', body, online.APP_REPOSITORY)
        release = {'tag_name': 'v0.7.1', 'body': 'Release notes', 'assets': [metadata]}
        with patch.object(online, 'latest_manifest', return_value=None), \
                patch.object(online, 'releases', return_value=[release]):
            offer = online.app_release(Client([Response(data=body)]), '0.7.1', 1)
            self.assertEqual(offer['revision'], 2)
            self.assertEqual(offer['notes'], 'Release notes')
            with self.assertRaises(ValueError):
                online.app_release(Client([Response(data=b'bad')]), '0.7.1', 1)

    def test_installed_revision_uses_the_matching_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'ddm-build.json'
            self.assertEqual(installed_revision(temporary, '0.7.1'), 0)
            for build, expected in (({'version': '0.7.1'}, 0), ({'version': '0.7.1', 'revision': 2}, 2),
                                    ({'version': '0.7.0', 'revision': 99}, 0)):
                path.write_text(json.dumps(build), encoding='utf-8-sig')
                self.assertEqual(installed_revision(temporary, '0.7.1'), expected)

    def test_same_version_install_stops_offering_and_rollback_restores_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root/'DD监控室CE.exe'
            old.write_bytes(b'old')
            build_path = root/'ddm-build.json'
            original = json.dumps({'version': '0.7.1', 'revision': 0}).encode()
            build_path.write_bytes(original)
            archive = root/'update.zip'
            build = {'version': '0.7.1', 'revision': 1, 'platform': 'windows-x64', 'update_protocol': 1}
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('app/ddm-build.json', json.dumps(build))
                package.writestr('app/DD监控室CE.exe', b'new')
                package.writestr('app/_internal/runtime.dll', b'runtime')
            with self.assertRaisesRegex(ValueError, '修订号'):
                update_install.prepare(archive, root, old, expected_version='0.7.1', expected_revision=2)
            plan = update_install.prepare(archive, root, old, expected_version='0.7.1', expected_revision=1)
            self.addCleanup(shutil.rmtree, Path(plan).parent)
            replace = os.replace
            def fail_exe(source, target):
                if Path(target) == old:
                    raise OSError('fixture file lock')
                return replace(source, target)
            with patch.object(update_install.os, 'replace', side_effect=fail_exe), self.assertRaises(OSError):
                update_install.apply_plan(plan)
            self.assertEqual(build_path.read_bytes(), original)
            self.assertIsNotNone(self.check(manifest(1), number=installed_revision(root, '0.7.1')))
            update_install.apply_plan(plan)
            self.assertEqual(old.read_bytes(), b'new')
            self.assertEqual(installed_revision(root, '0.7.1'), 1)
            self.assertIsNone(self.check(manifest(1), number=installed_revision(root, '0.7.1')))

    @unittest.skipUnless(shutil.which('powershell'), 'Windows release parameter validation')
    def test_release_parameters_resolve_revision_and_tag_together(self):
        source = (ROOT/'dev/build_release.ps1').read_text(encoding='utf-8-sig')
        parameters = source[source.index('param('):source.index('$ErrorActionPreference')]
        logic = source[source.index('if (-not $ReleaseTag)'):source.index('$display =')]
        quote = lambda value: "'"+str(value).replace("'", "''")+"'"
        probe = parameters + "\n$ErrorActionPreference='Stop'\n$repo="+quote(ROOT)+"\n$py="+quote(sys.executable)
        probe += "\n$version='v0.7.1'\n"+logic+"\n@{revision=$UpdateRevision;tag=$ReleaseTag} | ConvertTo-Json"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'parameters.ps1'
            path.write_text(probe, encoding='utf-8-sig')
            for arguments, expected in (([], 0), (['-UpdateRevision', '2'], 2),
                                        (['-ReleaseTag', 'v0.7.1-hotfix.3'], 3)):
                result = subprocess.run(['powershell', '-NoProfile', '-File', str(path), *arguments],
                                        capture_output=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['revision'], expected)
            bad = subprocess.run(['powershell', '-NoProfile', '-File', str(path), '-ReleaseTag',
                                  'v0.7.1-hotfix.2', '-UpdateRevision', '1'], capture_output=True)
            self.assertNotEqual(bad.returncode, 0)


if __name__ == '__main__':
    unittest.main()
