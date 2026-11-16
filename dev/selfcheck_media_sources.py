"""Real local reader delivery, independent consumers and nonblocking shutdown; no accounts."""
import io
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import media_sources


class Reader(io.BytesIO):
    def __init__(self, data=b'\x1aE\xdf\xa3fixture'):
        super().__init__(data)
        self.closed_event = threading.Event()

    def close(self):
        super().close()
        self.closed_event.set()

    def network_speed(self):
        return 8_000_000, 3


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.owner = SimpleNamespace(_active=True)
        self.addCleanup(media_sources.revoke, self.owner)

    def test_delivers_prepared_bytes_without_opening_another_reader(self):
        reader = Reader()
        url = media_sources.retain(lambda _cancelled: self.fail('opened twice'), reader, self.owner)
        source = media_sources.take(url)
        with urlopen(url) as response:
            self.assertEqual(response.headers['Content-Type'], 'video/x-matroska')
            self.assertEqual(response.read(), b'\x1aE\xdf\xa3fixture')
        self.assertTrue(reader.closed_event.wait(1))
        self.assertTrue(source.refresh_required.is_set())

    def test_recording_consumer_gets_an_independent_complete_stream(self):
        created = []
        def create(_cancelled):
            reader = Reader(b'new-reader')
            created.append(reader)
            return reader
        url = media_sources.retain(create, Reader(b'prepared'), self.owner)
        media_sources.take(url)
        with urlopen(url) as first:
            self.assertEqual(first.read(), b'prepared')
        with urlopen(url) as second:
            self.assertEqual(second.read(), b'new-reader')
        self.assertEqual(len(created), 1)

    def test_unclaimed_cancel_closes_prepared_stream(self):
        reader = Reader()
        url = media_sources.retain(lambda _cancelled: Reader(), reader, self.owner)
        media_sources.discard(url)
        self.assertTrue(reader.closed_event.wait(1))
        self.assertIsNone(media_sources.take(url))

    def test_revoke_active_and_pending_sources(self):
        first, second = Reader(), Reader()
        one = media_sources.retain(lambda _: Reader(), first, self.owner)
        two = media_sources.retain(lambda _: Reader(), second, self.owner)
        media_sources.take(one)
        media_sources.revoke(self.owner)
        self.assertTrue(first.closed_event.wait(1))
        self.assertTrue(second.closed_event.wait(1))
        self.assertIsNone(media_sources.take(one))
        self.assertIsNone(media_sources.take(two))

    def test_gui_stop_does_not_wait_for_blocked_reader_close(self):
        release = threading.Event()
        class Slow(Reader):
            def close(self):
                release.wait(2)
                super().close()
        reader = Slow()
        url = media_sources.retain(lambda _: Reader(), reader, self.owner)
        start = time.monotonic()
        media_sources.take(url).stop()
        self.assertLess(time.monotonic() - start, .1)
        release.set()
        self.assertTrue(reader.closed_event.wait(1))

    def test_closed_context_rejects_new_source_and_closes_reader(self):
        self.owner._active = False
        reader = Reader()
        with self.assertRaises(RuntimeError):
            media_sources.retain(lambda _: Reader(), reader, self.owner)
        self.assertTrue(reader.closed)

    def test_player_claims_source_without_relaying_it_twice(self):
        from unittest.mock import Mock, patch
        from ddm.player import TilePlayer
        source = Mock(url='http://127.0.0.1/media/fixture')
        player = Mock(spec=TilePlayer, decode_mode='auto', silent=False, diagnostic_room='youtube:fixture')
        player.PROFILE_HEADERS = TilePlayer.PROFILE_HEADERS
        player._refill_watch = Mock()
        player._watch = player._picture_watch = Mock()
        player.video_widget = Mock()
        with patch('ddm.media_sources.take', return_value=source), patch('ddm.hls_proxy.HlsProxy') as relay:
            TilePlayer._play_media(player, source.url, 'youtube', {}, [])
        self.assertIs(player._hls_proxy, source)
        self.assertEqual(player._media, source.url)
        relay.assert_not_called()

    def test_resolver_forwards_cancellation_and_discards_late_media(self):
        from ddm.bili_workers import StreamResolver
        from ddm.plugin_types import Platform
        for preview in (False, True):
            reader, observed = Reader(), []
            url = media_sources.retain(lambda _: Reader(), reader, self.owner)
            class Provider(Platform):
                def play_url(self, _room, _quality=10000, *, cancelled=None):
                    observed.append(cancelled)
                    worker.cancel()
                    return url, 10000, 'youtube', {}
                preview_url = play_url
            worker = StreamResolver('youtube:fixture', platform=Provider(), preview=preview)
            worker.run()
            self.assertTrue(callable(observed[0]))
            self.assertTrue(observed[0]())
            self.assertTrue(reader.closed_event.wait(1))
            self.assertIsNone(media_sources.take(url))


if __name__ == '__main__':
    unittest.main()
