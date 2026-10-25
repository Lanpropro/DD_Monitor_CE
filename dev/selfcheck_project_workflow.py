"""Repository workflow checks; no Qt, credentials, installed plugins or network."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectWorkflowTests(unittest.TestCase):
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
