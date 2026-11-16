"""文档结构检查：元信息、索引可达、相对链接与发布索引。

只读取 Git 已跟踪的 Markdown；不导入 Qt、不读取账号、不联网。
"""
import ast
from datetime import date
import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

TYPES = {"规范", "架构", "指南", "参考", "设计", "记录", "索引"}
STATUSES = {"草案", "维护中", "稳定", "冻结", "历史"}
NAV_HEADINGS = {"导读", "本页导航", "本页用法", "案例导航", "本页内容", "目录"}
MAINTAINED_TYPES = {"指南", "参考", "设计", "架构", "规范"}
METADATA = re.compile(
    r"^> 类型：(?P<type>\S+) ｜ 状态：(?P<status>\S+) ｜ 适用版本：(?P<version>[^｜]+) "
    r"｜ 更新：(?P<updated>\d{4}-\d{2}-\d{2}) ｜ 读者：(?P<readers>.+)$",
    re.MULTILINE,
)


def tracked(pattern="*.md"):
    output = subprocess.check_output(["git", "ls-files", "-z", pattern], cwd=ROOT)
    return [name for name in output.decode("utf-8").split("\0") if name]


def read(path):
    return path.read_text(encoding="utf-8")


def links(text):
    return re.findall(r"\]\(([^)]+)\)", text)


def resolve(source, target):
    destination = unquote(target.split("#", 1)[0])
    if not destination:
        return None
    return (source.parent / destination).resolve()


def slug(title):
    text = title.strip().lower()
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE)
    return text.strip().replace(" ", "-")


def anchors(path):
    found = {}
    result = set()
    for heading in re.findall(r"^#{1,6}\s+(.+)$", read(path), re.MULTILINE):
        base = slug(heading)
        count = found.get(base, 0)
        found[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")
    return result


def tracked_documents():
    return [ROOT / name for name in tracked("docs")
            if name.endswith(".md") and (ROOT / name).is_file()]


def maintained_documents():
    folders = {DOCS, DOCS / "development", DOCS / "architecture", DOCS / "standards", DOCS / "features"}
    paths = [path for path in tracked_documents()
             if path.parent in folders and path.name != "NOTICE.md"]
    paths.extend([DOCS / "releases/README.md", DOCS / "archive/README.md"])
    return sorted(paths)


def metadata(path):
    header = "\n".join(read(path).splitlines()[:8])
    match = METADATA.search(header)
    if match is None:
        return None
    return {name: value.strip() for name, value in match.groupdict().items()}


class DocumentStructureTests(unittest.TestCase):
    def test_maintained_documents_have_valid_metadata(self):
        for path in maintained_documents():
            relative = path.relative_to(ROOT).as_posix()
            with self.subTest(document=relative):
                text = read(path)
                self.assertTrue(text.startswith("# "), "document must start with a level-1 heading")
                data = metadata(path)
                self.assertIsNotNone(data, "missing metadata blockquote")
                self.assertIn(data["type"], TYPES)
                self.assertIn(data["status"], STATUSES)
                version = data["version"].strip()
                self.assertTrue(
                    version in ("全部版本", "不适用") or re.fullmatch(r"\d+\.\d+(\.x)?", version),
                    f"unexpected 适用版本: {version}")
                self.assertLessEqual(date.fromisoformat(data["updated"]), date.today())
                self.assertTrue(data["readers"])

    def test_every_tracked_document_is_reachable_from_the_index(self):
        start = DOCS / "README.md"
        seen, queue = set(), [start]
        while queue:
            path = queue.pop()
            if path in seen:
                continue
            seen.add(path)
            for target in links(read(path)):
                if "://" in target or target.startswith("mailto:"):
                    continue
                destination = resolve(path, target)
                if (destination is not None and destination.is_file()
                        and destination.suffix.lower() == ".md"
                        and destination.is_relative_to(DOCS)):
                    queue.append(destination)
        missing = sorted(path.relative_to(ROOT).as_posix()
                         for path in set(tracked_documents()) - seen)
        self.assertEqual(missing, [], "documents not linked from docs/README.md")

    def test_top_level_documents_and_folder_indexes_are_linked_directly(self):
        direct = set()
        for target in links(read(DOCS / "README.md")):
            destination = resolve(DOCS / "README.md", target)
            if destination is not None:
                direct.add(destination)
        required = {path for path in tracked_documents()
                    if path.parent == DOCS and path.name != "README.md"}
        required |= {DOCS / folder / "README.md"
                     for folder in ("development", "architecture", "standards", "features")
                     if (DOCS / folder / "README.md").is_file()}
        required |= {DOCS / "releases/README.md", DOCS / "archive/README.md"}
        missing = sorted(path.relative_to(ROOT).as_posix() for path in required - direct)
        self.assertEqual(missing, [], "top-level documents must be linked from the index")

    def test_relative_links_and_anchors_resolve(self):
        for relative in tracked():
            path = ROOT / relative
            if not path.is_file():
                continue
            for target in links(read(path)):
                target = target.strip()
                if not target or target.startswith("#") or "://" in target or target.startswith("mailto:"):
                    continue
                destination = resolve(path, target)
                if destination is None:
                    continue
                with self.subTest(document=relative, target=target):
                    if not destination.exists():
                        ignored = subprocess.run(
                            ["git", "check-ignore", "--", str(destination)],
                            cwd=ROOT, capture_output=True)
                        self.assertEqual(ignored.returncode, 0,
                                         f"missing link target: {target}")
                        continue
                    if "#" in target and destination.suffix.lower() == ".md":
                        fragment = unquote(target.split("#", 1)[1])
                        self.assertIn(fragment, anchors(destination),
                                      f"missing anchor: {target}")

    def test_release_index_covers_every_note(self):
        index = read(DOCS / "releases/README.md")
        notes = sorted(path.name for path in (DOCS / "releases").glob("*.md"))
        notes = [name for name in notes if name.startswith(("RELEASE-", "PLUGIN-"))]
        self.assertTrue(notes)
        missing = [name for name in notes if f"]({name})" not in index]
        self.assertEqual(missing, [], "release notes missing from the index")
        self.assertIn("](UNRELEASED.md)", index)
        module = ast.parse(read(ROOT / "ddm/version.py"))
        version = next(ast.literal_eval(node.value) for node in module.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "VERSION"
                               for target in node.targets))
        self.assertIn(f"RELEASE-v{version}.md", notes,
                      "current VERSION must have a release note before publishing")

    def test_new_documents_follow_file_naming(self):
        folders = {DOCS, DOCS / "development", DOCS / "architecture", DOCS / "standards", DOCS / "features"}
        for path in tracked_documents():
            if path.name in ("README.md", "NOTICE.md") or path.parent not in folders:
                continue
            with self.subTest(document=path.name):
                self.assertEqual(path.name, path.name.lower())
                self.assertNotIn(" ", path.name)

    def test_documents_do_not_contain_machine_specific_data(self):
        forbidden = ("C:\\Users\\", "F:\\CodexAppManager", "SESSDATA=", "bili_jct=")
        for path in tracked_documents():
            relative = path.relative_to(ROOT).as_posix()
            text = read(path)
            for pattern in forbidden:
                with self.subTest(document=relative, pattern=pattern):
                    self.assertNotIn(pattern, text)

    def test_long_documents_open_with_navigation(self):
        for path in maintained_documents():
            data = metadata(path)
            if data is None or data["type"] not in MAINTAINED_TYPES:
                continue
            lines = read(path).splitlines()
            if len(lines) <= 200:
                continue
            headings = set(re.findall(r"^##\s+(.+?)\s*$", "\n".join(lines), re.MULTILINE))
            with self.subTest(document=path.relative_to(ROOT).as_posix()):
                self.assertTrue(headings & NAV_HEADINGS,
                                "long document needs a reading guide or table of contents")

    def test_unreleased_notes_do_not_include_private_planning(self):
        notes = read(DOCS / "releases/UNRELEASED.md")
        self.assertNotIn("docs/local/", notes)
        self.assertNotIn("应迁入", notes)

    def test_plugin_reference_covers_public_events(self):
        constants = {}
        for name in ("plugins.py", "plugin_credentials.py"):
            module = ast.parse(read(ROOT / "ddm" / name))
            for node in module.body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.startswith("EVENT_"):
                            constants[target.id] = ast.literal_eval(node.value)
        module = ast.parse(read(ROOT / "ddm/plugins.py"))
        events = next(node.value for node in module.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "ALL_EVENTS"
                              for target in node.targets))
        reference = read(DOCS / "plugins.md")
        for event in events.elts:
            with self.subTest(event=event.id):
                self.assertTrue(f"`{constants[event.id]}`" in reference,
                                f"public event missing from the plugin reference: {constants[event.id]}")


if __name__ == "__main__":
    unittest.main()
