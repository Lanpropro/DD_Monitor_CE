"""Repository workflow checks; no Qt, credentials, installed plugins or network."""
import json
import os
from pathlib import Path
import re
import tempfile
import textwrap
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


class ProjectWorkflowTests(unittest.TestCase):
    def test_issue_forms_classify_feedback_without_claiming_a_fix(self):
        folder = ROOT / '.github/ISSUE_TEMPLATE'
        for filename, category in (('1-bug.yml', 'bug'), ('2-feature.yml', 'enhancement'), ('3-question.yml', 'question')):
            source = (folder / filename).read_text(encoding='utf-8')
            with self.subTest(filename=filename):
                self.assertRegex(source, r'(?m)^name: .{4,}$')
                self.assertRegex(source, r'(?m)^description: .+$')
                self.assertIn(f'labels: ["{category}", "待确认"]', source)
                self.assertNotIn('assignees:', source)
                ids = re.findall(r'^    id: ([a-z0-9_-]+)$', source, re.MULTILINE)
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(len(ids), len(re.findall(r'^  - type: (?:input|textarea|dropdown)$', source, re.MULTILINE)))
        bug = (folder / '1-bug.yml').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'^    id: ([a-z0-9_-]+)$', bug, re.MULTILINE), ['actual', 'reproducibility', 'attachments'])
        actual = bug.split('    id: actual\n', 1)[1].split('  - type:', 1)[0]
        self.assertIn('required: true', actual)
        attachments = bug.split('    id: attachments\n', 1)[1]
        self.assertIn('required: false', attachments)
        self.assertIn('无需重复填写', bug)
        self.assertIn('没有诊断包时', bug)
        self.assertIn('暂时无法复现', bug)
        self.assertIn('一般反馈无需启动专项', bug)
        selection = bug.split('    id: reproducibility\n', 1)[1].split('  - type:', 1)[0]
        self.assertIn('required: true', selection)
        self.assertEqual(re.findall(r'^        - (.+)$', selection, re.MULTILINE), ['稳定复现', '偶发', '尚不确定'])
        self.assertIn('blank_issues_enabled: true', (folder / 'config.yml').read_text(encoding='utf-8'))

    def test_issue_reproducibility_sync_changes_only_the_selected_label(self):
        source = (ROOT / '.github/workflows/issue-reproducibility.yml').read_text(encoding='utf-8')
        self.assertIn('types: [opened, edited]', source)
        self.assertIn('issues: write', source)
        self.assertNotIn('contents: write', source)
        self.assertNotIn('checkout@', source)
        code = compile(textwrap.dedent(source.split('        run: |\n', 1)[1]), 'issue-label-workflow', 'exec')
        cases = [
            ('### 复现情况\n\n稳定复现\n', [], '复现：稳定', []),
            ('### 复现情况\r\n\r\n偶发\r\n', [], '复现：偶发', []),
            ('### 复现情况\n\n尚不确定\n', [], '复现：不确定', []),
            ('### 复现情况\n\n稳定复现\n', ['复现：稳定', '复现：偶发'], None, ['复现：偶发']),
            ('### 复现情况\n\n偶发\n', ['复现：稳定'], '复现：偶发', ['复现：稳定']),
            ('旧反馈：偶发，目前无法复现', ['复现：稳定'], None, []),
            ('### 复现情况\n\n_No response_\n', ['复现：偶发'], None, []),
            ('### 复现情况\n\n处理中\n', [], None, []),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / 'event.json'
            event.write_text(json.dumps({'issue': {'number': 7, 'body': 'stale event body'}}), encoding='utf-8')
            for body, labels, added, removed in cases:
                with self.subTest(body=body, labels=labels):
                    calls = []
                    issue = {'body': body, 'labels': [{'name': x} for x in ['bug', '待验收'] + labels]}

                    def response(request, timeout):
                        calls.append(request)
                        result = MagicMock()
                        result.__enter__.return_value.read.return_value = json.dumps(issue).encode() if request.method == 'GET' else b''
                        return result

                    with patch.dict(os.environ, {'GITHUB_EVENT_PATH': str(event), 'GITHUB_API_URL': 'https://api.github.invalid',
                                                 'GITHUB_REPOSITORY': 'fixture/repo', 'GH_TOKEN': 'fixture-token'}), \
                            patch('urllib.request.urlopen', side_effect=response):
                        exec(code, {})
                    self.assertEqual(calls[0].method, 'GET')
                    posts = [json.loads(r.data) for r in calls if r.method == 'POST']
                    self.assertEqual(posts, [{'labels': [added]}] if added else [])
                    deletes = [unquote(r.full_url.rsplit('/', 1)[1]) for r in calls if r.method == 'DELETE']
                    self.assertEqual(deletes, removed)
                    self.assertFalse(any(r.method == 'PUT' for r in calls))

    def test_contribution_rules_use_develop_and_function_branches(self):
        source = (ROOT / 'CONTRIBUTING.md').read_text(encoding='utf-8')
        for text in ('`main`', '`develop`', 'function/', 'Draft PR'):
            self.assertIn(text, source)
        self.assertNotIn('当前主要开发分支是 `main`', source)
        readme = (ROOT / 'docs/README.md').read_text(encoding='utf-8')
        self.assertIn('../CONTRIBUTING.md', readme)

    def test_existing_agent_rules_keep_basic_repository_conventions(self):
        source = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        for text in ('`main`', 'function/', 'Draft PR'):
            self.assertIn(text, source)

    def test_contribution_guide_preserves_shared_history_and_snapshot_scope(self):
        source = (ROOT / 'CONTRIBUTING.md').read_text(encoding='utf-8')
        for text in ('Squash and merge', '--force-with-lease', 'git revert',
                     'release/', 'archive/',
                     'git pull --ff-only origin develop'):
            self.assertIn(text, source)

    def test_daily_entry_and_release_use_the_same_development_source(self):
        source = (ROOT / 'CONTRIBUTING.md').read_text(encoding='utf-8')
        for text in ('根目录 `run.cmd`', '集成回根目录', '完整开发源码', 'PySide6 6.11.2'):
            self.assertIn(text, source)
        self.assertFalse((ROOT / 'dev/restart-client.ps1').exists())

    def test_old_release_folders_are_archived_after_verification(self):
        source = (ROOT / 'docs/development/workspace-maintenance.md').read_text(encoding='utf-8')
        for text in ('最新正式版本', '旧版发布目录归档为同名 ZIP',
                     '核对文件清单及内容一致后再删除原目录', '解压到 `work/`'):
            self.assertIn(text, source)

    def test_pr_template_documents_target_validation_and_dependencies(self):
        source = (ROOT / '.github/PULL_REQUEST_TEMPLATE.md').read_text(encoding='utf-8')
        self.assertIn('目标分支为 `develop`', source)
        self.assertIn('由 `develop` 创建面向 `main` 的发布 PR', source)
        self.assertNotIn('目标分支为 `main`', source)
        self.assertGreaterEqual(source.count('- [ ]'), 4)
        self.assertIn('PR', source)

    def test_ci_is_read_only_and_pins_actions_to_commits(self):
        source = (ROOT / '.github/workflows/repository-checks.yml').read_text(encoding='utf-8')
        self.assertIn('pull_request:', source)
        self.assertIn('contents: read', source)
        self.assertIn('persist-credentials: false', source)
        self.assertIn("'function/**'", source)
        self.assertIn('branches: [main, develop]', source)
        self.assertIn("branches: [main, develop, 'function/**']", source)
        self.assertNotIn('pull_request_target:', source)
        self.assertNotIn('secrets.', source)
        for action in re.findall(r'uses:\s*(\S+)', source):
            self.assertRegex(action, r'^[\w/-]+@[0-9a-f]{40}$')
        self.assertIn('python dev/run_checks.py --suite repository', source)
        self.assertIn('python -m compileall -q ddm blivedm main.py', source)


if __name__ == '__main__':
    unittest.main()
