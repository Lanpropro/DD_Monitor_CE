"""Check the auxiliary inventory against Git without reading user data."""
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryMapTests(unittest.TestCase):
    def test_all_tracked_auxiliary_files_are_documented(self):
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
        runtime_roots = ("ddm/", "blivedm/", "assets/", "plugins_user/")
        runtime_files = {"main.py", "requirements.txt", "run.cmd",
                         "run-console.cmd", "favicon.ico"}
        expected = {p for p in tracked if p and
                    not p.startswith(runtime_roots) and p not in runtime_files}
        content = (ROOT / "docs/repository-map.md").read_text(encoding="utf-8")
        inventory = content.split("## 已跟踪的其他文件：逐项标注", 1)[1]
        inventory = inventory.split("## 仅本机存在的其他资料", 1)[0]
        listed = re.findall(r"^- `([^`]+)`$", inventory, re.MULTILINE)
        self.assertEqual(set(listed), expected)
        self.assertEqual(len(listed), len(set(listed)), "Duplicate inventory path")


if __name__ == "__main__":
    unittest.main()
