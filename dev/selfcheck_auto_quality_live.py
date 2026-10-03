"""联网验收：真实 VLC 解码、真实分片限速降档、恢复升档与自动意图保存。"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import config, hls_proxy, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.auto_quality import AUTO_QUALITY  # noqa: E402
from selfcheck_platform_preview_live import relay_stopped, stats, wait_for  # noqa: E402


def main():
    rid = sys.argv[1]
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    state = {"plugins_enabled": ["global_live"], "settings": {"recording_enabled": False,
        "recording_replay_enabled": False, "preview_on_hover": False, "danmaku_enabled": False}}
    original_get = hls_proxy.requests.get
    limit = [0]
    def download(*args, **kwargs):
        response = original_get(*args, **kwargs)
        if kwargs.get("stream") and "mpegurl" not in response.headers.get("Content-Type", "").lower():
            original_chunks = response.iter_content
            def chunks(*chunk_args, **chunk_kwargs):
                for chunk in original_chunks(*chunk_args, **chunk_kwargs):
                    if limit[0]:
                        time.sleep(len(chunk) * 8 / limit[0])
                    yield chunk
            response.iter_content = chunks
        return response
    with patch("ddm.app.QTimer.singleShot"), patch("ddm.app.MainWindow.sync_danmaku"), \
            patch.object(hls_proxy.requests, "get", side_effect=download):
        window = MainWindow([], [], state=state, layout_id="corner")
        window.resize(1000, 700)
        window.show()
        window._poll_timer.stop()
        window._stats_timer.stop()
        window._audio_audit_timer.stop()  # 静音自检不反复输出 VLC 原生 aout 的状态
        try:
            platform = window.plugins.platform_for(rid)
            room = platform.room_info(rid).as_dict()
            assert room["live"], "The supplied room is offline"
            tile = window.wall.tiles[0]
            tile.set_room(room)
            tile.set_muted(True)
            window.start_tile(tile)
            wait_for(app, lambda: tile in window.players and stats(window.players[tile]).displayed_pictures > 30, 50)
            tiers = [item for item in tile.quality_options if item["qn"] != AUTO_QUALITY]
            assert len(tiers) > 1 and tile.quality == AUTO_QUALITY
            player = window.players[tile]
            reported = [0]
            def diagnostic_highest():
                if time.monotonic() - reported[0] >= 10:
                    reported[0] = time.monotonic()
                    proxy = player._relay._hls_proxy if player._relay else None
                    print("TRACE:", tile._quality_text(), player.state,
                          "network", proxy.network_speed() if proxy else None,
                          "bandwidths", [item["bandwidth"] for item in tiers], flush=True)
                return tile.actual_quality == 10000 and tile not in window._resolvers and stats(player).displayed_pictures > 30
            def decoded_frames(count):
                media, previous, advanced = player._media, stats(player).displayed_pictures, 0
                def progressing():
                    nonlocal media, previous, advanced
                    current = stats(player).displayed_pictures
                    if player._media is media:
                        advanced += max(0, current - previous)
                    else:
                        media = player._media  # 自动调档会重建 media，VLC 计数从零开始
                    previous = current
                    return advanced >= count
                wait_for(app, progressing, 60)
            print(f"PASS: {rid} automatic startup, actual {tile._quality_text()}, native {player.player.video_get_size(0)}", flush=True)
            wait_for(app, diagnostic_highest, 200)
            decoded_frames(60)
            print(f"PASS: real download samples select highest tier {tile._quality_text()}, speed={player._relay._hls_proxy.network_speed()}", flush=True)
            controller = player.auto_quality
            # 限速实际分片迭代，保留真实请求/清单/VLC/画质策略。
            limit[0] = max(500000, tiers[-1]["bandwidth"] * 1.4)
            wait_for(app, lambda: tile.actual_quality != 10000 and tile not in window._resolvers
                     and stats(player).displayed_pictures > 30, 90)
            print(f"PASS: limited downloads ({limit[0]:.0f} bit/s) downshift to {tile._quality_text()}", flush=True)
            assert tile.quality == AUTO_QUALITY and player.auto_quality is controller
            limit[0] = 0
            wait_for(app, diagnostic_highest, 200)
            decoded_frames(90)
            saved = window.current_state()
            _, slots = config.build_rooms(saved)
            assert slots[0]["quality"] == AUTO_QUALITY
            assert tile._quality_text().startswith("自动 · ")
            print("PASS: recovered network restores highest tier, native frames continue and automatic choice persists", flush=True)
            relay = player._relay
        finally:
            limit[0] = 0
            window.close()
            app.processEvents()
        relay_stopped(relay)
    print("PASS: live adaptive quality and process/proxy cleanup", flush=True)


if __name__ == "__main__":
    main()
