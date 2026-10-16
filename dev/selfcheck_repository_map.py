"""Check the auxiliary inventory against Git without reading user data."""
import ast
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


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

    def test_document_index_links_resolve(self):
        for name in ("docs/README.md", "docs/repository-cleanup-review.md", "README.md",
                     "docs/plugins.md"):
            path = ROOT / name
            content = path.read_text(encoding="utf-8")
            for target in re.findall(r"\]\(([^)]+)\)", content):
                if "://" in target or target.startswith("#"):
                    continue
                with self.subTest(document=name, target=target):
                    destination = path.parent / target.split("#", 1)[0]
                    if not destination.exists():
                        # Local notes are intentionally absent from clean clones.
                        ignored = subprocess.run(
                            ["git", "check-ignore", "--", str(destination)], cwd=ROOT,
                            capture_output=True)
                        self.assertEqual(ignored.returncode, 0, target)

    def test_current_notes_source_and_portable_layouts(self):
        # Exercise the real UI method with label doubles; no QApplication,
        # plugin loading, network or real config is needed for file resolution.
        tree = ast.parse((ROOT / "ddm/online_ui.py").read_text(encoding="utf-8"))
        page = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "AppUpdatePage")
        method = next(node for node in page.body
                      if isinstance(node, ast.FunctionDef) and node.name == "show_current_notes")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope = {"Path": Path, "config": SimpleNamespace(REPO=directory),
                     "version": SimpleNamespace(VERSION="test")}
            exec(compile(ast.Module(body=[method], type_ignores=[]), "online_ui.py", "exec"), scope)
            ui = SimpleNamespace(notes_title=Mock(), notes=Mock())
            show = scope["show_current_notes"]
            show(ui)
            self.assertIn("本地未附带", ui.notes.setMarkdown.call_args.args[0])
            portable = root / "RELEASE-vtest.md"
            portable.write_text("# Portable notes", encoding="utf-8-sig")
            show(ui)
            ui.notes.setMarkdown.assert_called_with("# Portable notes")
            source = root / "docs/releases/RELEASE-vtest.md"
            source.parent.mkdir(parents=True)
            source.write_text("# Source notes", encoding="utf-8")
            show(ui)
            ui.notes.setMarkdown.assert_called_with("# Source notes")
            portable.unlink()
            show(ui)
            ui.notes.setMarkdown.assert_called_with("# Source notes")

    def test_portable_build_copies_relocated_documents(self):
        source = (ROOT / "dev/build_release.ps1").read_text(encoding="utf-8")
        start = source.index('    foreach ($file in @("LICENSE", "docs/NOTICE.md"')
        stop = source.index('    $exeReadme =', start)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs/releases").mkdir(parents=True)
            expected = {"LICENSE": "License", "NOTICE.md": "Notice",
                        "RELEASE-vtest.md": "Release"}
            for path, content in (("LICENSE", "License"), ("docs/NOTICE.md", "Notice"),
                                  ("docs/releases/RELEASE-vtest.md", "Release")):
                (root / path).write_text(content, encoding="utf-8")
            output = root / "portable"
            output.mkdir()
            script = root / "copy-documents.ps1"
            script.write_text('param($repo, $exeDir, $version)\n$ErrorActionPreference = "Stop"\n'
                              + source[start:stop], encoding="utf-8-sig")
            result = subprocess.run(["powershell", "-NoProfile", "-File", str(script),
                                     "-repo", str(root), "-exeDir", str(output),
                                     "-version", "vtest"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual({p.name: p.read_text(encoding="utf-8")
                              for p in output.iterdir()}, expected)


if __name__ == "__main__":
    unittest.main()
