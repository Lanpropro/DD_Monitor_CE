"""Early matching, bucket edges, stale/replayed evidence and confidence admission."""
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plugins_user._match_sync.engine import Alignment, Match, Sample, SIGNATURE_BITS, match_scenes


def main():
    rng = random.Random(20261006)
    reference = [Sample(100 + i * .5, rng.getrandbits(SIGNATURE_BITS), 20) for i in range(40)]
    for count in (8, 10):
        early = reference[:count]
        delayed = [Sample(s.time + 5.25 + (.04 if i % 2 else -.04), s.signature, 20)
                   for i, s in enumerate(early)]
        result = match_scenes(early, delayed)
        assert result.lag is not None and abs(result.lag - 5.25) < .05, result
        assert result.confidence >= .65
    print("PASS: eight/ten samples across the half-second bucket edge establish the correct 5.25s lag")

    delayed = [Sample(s.time + 4.3, s.signature ^ rng.getrandbits(40), 20) for s in reference]
    result = match_scenes(reference, delayed)
    assert result.lag is not None and abs(result.lag - 4.3) < .01, result
    reverse = match_scenes(delayed, reference)
    assert reverse.lag is not None and abs(reverse.lag + 4.3) < .01, reverse

    # Old common footage must not outweigh the newest common sequence.
    other = [Sample(s.time + 5, s.signature, 20) for s in reference[:34]]
    other += [Sample(s.time + 7, s.signature ^ rng.getrandbits(16), 20) for s in reference[28:]]
    result = match_scenes(reference, other)
    assert result.lag is not None and abs(result.lag - 7) < .01, result
    print("PASS: compression noise, reversed feeds and newer changed latency retain the correct sign and lag")

    mask = (1 << 256) - 1
    overlay_ref = [Sample(s.time, s.signature & mask, 20) for s in reference]
    overlay_other = [Sample(s.time + 6, s.signature & mask | rng.getrandbits(256) << 256, 20)
                     for s in reference]
    result = match_scenes(overlay_ref, overlay_other)
    assert result.lag is not None and abs(result.lag - 6) < .01, result
    print("PASS: motion confined to one feed's unrelated overlay does not drown out shared scene changes")

    stale = [Sample(s.time + 5, s.signature, 20) for s in reference[:20]]
    stale += [Sample(s.time + 5, rng.getrandbits(SIGNATURE_BITS), 20) for s in reference[20:]]
    assert match_scenes(reference, stale).lag is None, "An old common scene cannot claim current alignment"
    repeated = [Sample(100 + i * .5, reference[i % 12].signature, 20) for i in range(64)]
    assert match_scenes(repeated, repeated).lag is None, "Periodic replay is ambiguous"
    frozen = [Sample(100 + i * .5, reference[0].signature, 20) for i in range(40)]
    assert match_scenes(frozen, frozen).lag is None
    assert match_scenes(reference, [Sample(s.time, rng.getrandbits(SIGNATURE_BITS), 20) for s in reference]).lag is None

    alignment = Alignment()
    alignment.select_reference("main")
    for _ in range(4):
        assert not alignment.accept("other", Match(20, .3, "weak evidence"))
    assert "other" not in alignment.lags
    assert not alignment.accept("other", Match(7, .9, "confirmed"))
    assert alignment.accept("other", Match(7.1, .9, "confirmed"))
    previous = dict(alignment.lags)
    for _ in range(4):
        assert not alignment.accept("other", Match(30, .3, "weak replacement"))
    assert alignment.lags == previous
    alignment.manual_locked = True
    assert not alignment.accept("other", Match(30, 1, "cannot replace manual lock"))
    assert alignment.lags == previous
    print("PASS: stale/static/unrelated/repeated footage rejected; weak evidence cannot establish or replace alignment")


if __name__ == "__main__":
    main()
