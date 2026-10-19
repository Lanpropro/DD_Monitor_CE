"""Check repository cleanup without reading user settings or media."""
import fnmatch
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ONLY = (
    "HANDOFF-*.md", "docs/HANDOFF-*.md", "docs/local/*", "videos/*",
    "docs/VIDEO-*.md", "docs/PROMO-*.md", "dev/*promo*",
    "dev/*highlight*", "dev/*videotogether*", "dev/test_video_*.py",
    "dev/preview_*.py", "dev/watch_layout_preview.py", "dev/run-preview.cmd", "dev/make_shots.py",
    "dev/thumb_sheet.py", "dev/mock_portrait2.py",
    "docs/portrait-bar.png", "docs/portrait-current.png", "docs/portrait-mock.png",
    "dev/mock_portrait.py", "dev/portrait_mock.html", "console.log*",
    "utils/*", "plugins_user/.updates/*", "plugins_user/match_sync/*",
)
REQUIRED = (
    "main.py", "requirements.txt", "run.cmd", "run-console.cmd",
    "LICENSE", "docs/NOTICE.md", "favicon.ico", "assets/logo.png",
    "CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md", ".github/workflows/repository-checks.yml",
    ".gitattributes",
    "dev/README.md", "dev/run_checks.py", "dev/checks/suites.json", "dev/checks/bootstrap.py",
    "dev/checks/README.md", "docs/development/testing.md",
    "ddm/app.py", "ddm/widgets.py", "blivedm/clients/web.py",
    "dev/build_release.ps1", "dev/build_windows_version.py",
    "dev/pyi_rth_pyside6_paths.py", "dev/selfcheck_video_danmaku.py",
    "docs/overview1_Landscape_mode.png", "docs/overview2_Landscape_mode.png",
    "docs/overview1_Portrait_Mode.png", "README.md",
)


class RepositoryFilesTests(unittest.TestCase):
    def test_local_material_is_not_in_source_manifest(self):
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
        leaks = [path for path in tracked if path and any(
            fnmatch.fnmatchcase(path, pattern) for pattern in LOCAL_ONLY)]
        self.assertEqual(leaks, [], "Local material would enter the source manifest")

    def test_local_material_cannot_be_accidentally_added(self):
        paths = [pattern.replace("*", "cleanup-fixture") for pattern in LOCAL_ONLY]
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--stdin", "-z"], cwd=ROOT,
            input=("\0".join(paths) + "\0").encode("utf-8"),
            capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(result.stdout.decode("utf-8").rstrip("\0").split("\0")),
                         set(paths))

    def test_runtime_build_licenses_and_readme_images_remain(self):
        for path in REQUIRED:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
