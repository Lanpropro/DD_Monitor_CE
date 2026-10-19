"""Repository workflow checks; no Qt, credentials, installed plugins or network."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectWorkflowTests(unittest.TestCase):
    def test_contributor_and_agent_rules_use_main_and_function_branches(self):
        for name in ('CONTRIBUTING.md', 'AGENTS.md'):
            with self.subTest(name=name):
                source = (ROOT / name).read_text(encoding='utf-8')
                self.assertIn('`main`', source)
                self.assertIn('function/', source)
                self.assertIn('Draft PR', source)
        readme = (ROOT / 'docs/README.md').read_text(encoding='utf-8')
        self.assertIn('../CONTRIBUTING.md', readme)

    def test_pr_template_documents_target_validation_and_dependencies(self):
        source = (ROOT / '.github/PULL_REQUEST_TEMPLATE.md').read_text(encoding='utf-8')
        self.assertIn('`main`', source)
        self.assertGreaterEqual(source.count('- [ ]'), 4)
        self.assertIn('PR', source)

    def test_ci_is_read_only_and_pins_actions_to_commits(self):
        source = (ROOT / '.github/workflows/repository-checks.yml').read_text(encoding='utf-8')
        self.assertIn('pull_request:', source)
        self.assertIn('contents: read', source)
        self.assertIn('persist-credentials: false', source)
        self.assertIn("'function/**'", source)
        self.assertNotIn('pull_request_target:', source)
        self.assertNotIn('secrets.', source)
        for action in re.findall(r'uses:\s*(\S+)', source):
            self.assertRegex(action, r'^[\w/-]+@[0-9a-f]{40}$')
        self.assertIn('dev.selfcheck_repository_files dev.selfcheck_project_workflow', source)
        self.assertIn('python -m compileall -q ddm blivedm main.py', source)


if __name__ == '__main__':
    unittest.main()
