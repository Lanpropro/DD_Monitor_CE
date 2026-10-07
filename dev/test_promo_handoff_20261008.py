"""Validate the promo handoff's local entry points and task boundaries."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIEF = ROOT / "docs/HANDOFF-PROMO-2026-10-08.md"


class PromoHandoffTests(unittest.TestCase):
    def test_takeover_records_verification_and_replacement_entries(self):
        brief = BRIEF.read_text(encoding="utf-8")
        current = (ROOT / "PROJECT_STATE.md").read_text(encoding="utf-8").split("\n---\n", 1)[0]
        for record in ("已接手", "01a11758-8cca-7382-a41f-0a33ba0d0491",
                       "88733939", "41.515–49.091", "49.091–56.061",
                       "compositions/audition.html", "compositions/updates.html",
                       "未验证浏览器播放"):
            with self.subTest(record=record):
                self.assertIn(record, brief)
                self.assertIn(record, current)
        for composition in ("audition", "updates"):
            self.assertTrue((ROOT / "videos/dd-monitor-ce-plugins-promo/compositions" /
                             f"{composition}.html").is_file())

    def test_handoff_matches_registered_task_and_preserves_history(self):
        brief = BRIEF.read_text(encoding="utf-8")
        state = (ROOT / "PROJECT_STATE.md").read_text(encoding="utf-8")
        current = state.split("\n---\n", 1)[0]
        self.assertIn("PROMO-20261008-01", brief)
        self.assertIn("PROMO-20261008-01", current)
        self.assertIn("docs/HANDOFF-PROMO-2026-10-08.md", current)
        for historical in ("PLATFORM-FOLLOWS-20261005-01", "WEBSITE-20261003-01"):
            self.assertIn(historical, state)
        for decision in ("41.515–49.091", "1+5", "6de857d", "刷新后不再出现",
                         "不自行恢复已删除文本", "无有效直播声音"):
            self.assertIn(decision, brief)

    def test_required_local_artifacts_are_available(self):
        for relative in (
            "videos/dd-monitor-ce-plugins-promo/index.html",
            "videos/dd-monitor-ce-plugins-promo/renders/sample-v7.mp4",
            "videos/dd-monitor-ce-plugins-promo/assets/domestic-apex-v7.mp4",
            "videos/dd-monitor-ce-plugins-promo/assets/global-stitched.mp4",
            "videos/dd-monitor-ce-plugins-promo/assets/match-continuous.mp4",
            "videos/dd-monitor-ce-plugins-promo/.media/audio/bgm/bgm_001.mp3",
            "videos/dd-monitor-ce-plugins-promo/PREVIEW-TROUBLESHOOTING.md",
            "Video_reference/国内apex1+5 重置.mp4",
            "Video_reference/二路直播对齐.mp4",
            "results/dd-monitor-ce-promo-archive-2026-10-04.zip",
            "work/limited-runtime/check.json",
        ):
            with self.subTest(path=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
