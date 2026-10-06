"""Fine scene timing with phase, tone, compression noise and guarded tracking."""
from pathlib import Path
import math
import os
import random
import sys
import tempfile
import time
from collections import deque
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from plugins_user._match_sync.engine import Alignment, AudioRing, Match, Sample, refine_match


def descriptor(t):
    return bytes(round(128 + 55 * math.sin(t * (1.3 + i * .043) + i * 1.7)
                       + 25 * math.sin(t * (3 + i * .017) - i)) for i in range(256))


def samples(lag=0, phase=0, noise=0, start=0, count=201):
    rng = random.Random(17)
    result = []
    for index in range(count):
        content = start + phase + index * .05
        feature = bytes(max(0, min(255, value + rng.randint(-noise, noise))) for value in descriptor(content))
        result.append(Sample(100 + content + lag, index, 20, feature))
    return result


def gui_checks():
    from PySide6.QtWidgets import QApplication, QWidget
    from ddm import plugins
    from dev.selfcheck_match_sync import FakeChat, FakeDecoder
    from plugins_user._match_sync import viewer as module

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda _self: None):
        host = QWidget()
        host.settings = {}
        manager = plugins.PluginManager(window=host, plugins_dir=root)
        viewer = module.Viewer(plugins.PluginContext(manager, "refinement_check"), {})
        try:
            viewer.add_room("1", {"alias": "Main"})
            viewer.add_room("2", {"alias": "Other"})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            for key, detail in (("1", samples()), ("2", samples(7.237, .027, 2))):
                history = viewer.rows[key].decoder.history
                history.origin = 100
                history.samples = deque(detail[::10])
                history.details = deque(detail)
            viewer.alignment.lags["2"] = 7.537
            with patch.object(viewer.audio, "clock", return_value=118):
                for _ in range(3):
                    viewer.canvas.frame_key = 118 + viewer.shifts()["1"]
                    viewer.analyse()
                    assert viewer.matching
                    deadline = time.monotonic() + 3
                    while viewer.matching and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(.005)
                    assert not viewer.matching, "Fine worker did not deliver to the GUI"
            row = viewer.rows["2"]
            assert abs(viewer.alignment.lags["2"] - 7.237) < .06
            assert "播放进度已复核" in row.match_text and "剩余误差" in row.match_text, row.match_text
            viewer.canvas.frame_key -= 1
            with patch.object(viewer.audio, "clock", return_value=118):
                viewer.analyse()
                deadline = time.monotonic() + 3
                while viewer.matching and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.005)
                assert not viewer.matching
            assert "播放进度已复核" not in row.match_text and "1.00" in row.match_text, row.match_text
            previous, status = dict(viewer.alignment.lags), row.match_text
            viewer._matched(viewer.generation - 1, {"2": Match(30, 1, "stale", refined=True)})
            assert viewer.alignment.lags == previous and row.match_text == status
            row.delay.setValue(.4)
            assert viewer.alignment.manual_locked and not viewer.alignment.automatic
            viewer._matched(viewer.generation, {"2": Match(30, 1, "manual", refined=True)})
            assert viewer.alignment.lags == previous and "已锁定" in row.match_text
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print("PASS: asynchronous fine correction, actual held-picture error, stale generation rejection and manual lock")


def main():
    ring = AudioRing(seconds=8 / 48000)
    ring.append_at(3, b"\x01\x00\x02\x00" * 2)
    assert ring.read(0, 5) == bytes(12) + b"\x01\x00\x02\x00" * 2
    ring.append_at(4, b"\x03\x00\x04\x00" * 2)
    assert ring.end == 6 and ring.read(5, 1) == b"\x03\x00\x04\x00"
    ring.append_at(100, b"\x05\x00\x06\x00")
    assert ring.read(93, 8) == bytes(28) + b"\x05\x00\x06\x00"
    print("PASS: audio PTS preserve gaps and overlaps without replaying PCM or allocating unbounded silence")
    reference = samples()
    for lag in (7.237, -4.183, .137, 15.417):
        for phase in (.027, .041):
            other = samples(lag, phase, 2)
            coarse = Match(round(lag * 2) / 2, .9, "coarse")
            result = refine_match(coarse, reference, other)
            assert result.lag is not None and abs(result.lag - lag) <= .06, (lag, phase, result)
            assert result.refined and result.confidence >= .65
    print("PASS: positive/negative/subsecond/large lags refine within 60ms across sampling phases and compression noise")
    assert refine_match(Match(7, .9, "coarse"), reference[:20], samples(7)[:20]).lag is None
    frozen = [Sample(s.time, 0, 20, bytes([128]) * 256) for s in reference]
    assert refine_match(Match(0, .9, "coarse"), frozen, frozen).lag is None
    unrelated = [Sample(s.time, s.signature, 20, descriptor((s.time - 100) * 1.7 + 25)) for s in reference]
    assert refine_match(Match(0, .9, "coarse"), reference, unrelated).lag is None
    repeated = [Sample(s.time, i, 20, descriptor((i % 4) * .05)) for i, s in enumerate(reference)]
    assert refine_match(Match(0, .9, "coarse"), repeated, repeated).lag is None
    assert refine_match(Match(None, 0, "multiple", candidates=(0, 1)), repeated, repeated).lag is None
    changed = samples(7)
    changed[-40:] = [Sample(s.time, s.signature, s.texture, descriptor((s.time - 107) + 2)) for s in changed[-40:]]
    assert refine_match(Match(7, .9, "coarse"), reference, changed).lag is None
    print("PASS: short/static/unrelated/repeated and mixed-latency sequences cannot establish a fine lock")
    alignment = Alignment()
    alignment.select_reference("main")
    first = Match(7.237, .9, "fine", refined=True)
    assert not alignment.accept("other", first)
    assert alignment.accept("other", first)
    assert alignment.accept("other", Match(7.337, .9, "drift", refined=True))
    assert abs(alignment.lags["other"] - 7.262) < .001, "Small corrections must stay inside picture prefetch"
    assert not alignment.accept("other", Match(12, .9, "jump", refined=True))
    assert alignment.accept("other", Match(12.03, .9, "jump", refined=True))
    previous = dict(alignment.lags)
    alignment.manual_locked = True
    assert not alignment.accept("other", Match(30, 1, "manual wins", refined=True))
    assert alignment.lags == previous
    print("PASS: consecutive fine confirmation, gradual small correction, confirmed large jump and manual priority")
    gui_checks()


if __name__ == "__main__":
    main()
