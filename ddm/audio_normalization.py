"""Playback loudness measurement and user-defined gain response in decibels."""
import math
import time

from PySide6.QtCore import QObject, QTimer


# These are application presets inspired by published product goals, not vendor algorithms.
PRESETS = {
    'gentle': ('平缓（默认）', -18., 3., 18., 2., 2., 10.),
    'spotify': ('Spotify 参考', -14., 3., 18., 3., 2., 12.),
    'netflix': ('Netflix 参考', -24., 3., 18., 4., 3., 15.),
    'apple_music': ('Apple Music 参考', -18., 3., 18., 3., 2., 12.),
}
FIELDS = ('target_lufs', 'max_boost_db', 'max_cut_db', 'attack', 'hold', 'release')
LIMITS = ((-30., -10.), (0., 12.), (0., 24.), (.1, 10.), (0., 10.), (.2, 30.))


def preset_curve(name='gentle'):
    return dict(preset=name, **dict(zip(FIELDS, PRESETS[name][1:])))


def normalize_curve(value=None):
    value = value if isinstance(value, dict) else {}
    name = value.get('preset', 'gentle')
    if name not in (*PRESETS, 'custom'):
        name = 'custom'
    result = preset_curve(name if name in PRESETS else 'gentle')
    result['preset'] = name
    for key, (low, high) in zip(FIELDS, LIMITS):
        number = value.get(key)
        if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number):
            result[key] = round(min(high, max(low, number)), 2)
    return result


class GainResponse:
    """Attack/release reach 95% of a constant target change in the chosen time."""

    def __init__(self, settings=None):
        self.settings = normalize_curve(settings)
        self.gain = 0.
        self.hold_remaining = self.settings['hold']

    def step(self, desired, elapsed, *, active=True):
        if not active:
            self.hold_remaining = self.settings['hold']
            return self.gain
        settings = self.settings
        desired = min(settings['max_boost_db'], max(-settings['max_cut_db'], desired))
        if desired < self.gain - .05:
            self.hold_remaining = settings['hold']
            duration = settings['attack']
        elif desired > self.gain + .05:
            waiting = min(self.hold_remaining, elapsed)
            self.hold_remaining -= waiting
            elapsed -= waiting
            duration = settings['release']
        else:
            return self.gain
        self.gain += (desired - self.gain) * (1 - math.exp(-3 * elapsed / duration))
        return self.gain

    def measure(self, loudness, elapsed):
        # Silence and very low ambience must not drive gain recovery or amplification.
        return self.step(self.settings['target_lufs'] - loudness, elapsed,
                         active=math.isfinite(loudness) and loudness > -50.)


def response_preview(settings):
    """The same response used by playback, for a 6 dB rise followed by recovery."""
    curve = normalize_curve(settings)
    response = GainResponse(curve)
    points = [(0., 0.)]
    total = curve['attack'] + curve['hold'] + curve['release']
    for index in range(1, 401):
        elapsed = total / 400
        instant = index * elapsed
        gain = response.step(-min(6., curve['max_cut_db']) if instant <= curve['attack'] else 0., elapsed)
        points.append((instant, gain))
    return points


class LiveVolumeNormalizer(QObject):
    """GUI-owned timer; measurements and gain commands stay on the owning Qt thread."""

    def __init__(self, owner):
        super().__init__(owner)
        self.response = GainResponse()
        self.last_gain = None
        self.last_time = 0.
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

    def reset(self):
        owner = self.parent()
        self.timer.stop()
        self.response = GainResponse(owner.normalization_curve)
        self.last_gain = None
        self.last_time = time.monotonic()
        if owner.volume_normalization and owner.player is not None:
            self.timer.start()

    def tick(self):
        owner = self.parent()
        core = owner.player
        now = time.monotonic()
        elapsed, self.last_time = min(.25, now - self.last_time), now
        if core is None or owner._released or not owner.volume_normalization:
            self.timer.stop()
            return
        if owner.paused or owner._prop('core-idle', True):
            return
        try:
            metadata = core._get_property('af-metadata/ddm_meter')
            if not isinstance(metadata, dict) or 'lavfi.r128.M' not in metadata:
                return
            gain = self.response.measure(float(metadata['lavfi.r128.M']), elapsed)
            if self.last_gain is None or abs(gain - self.last_gain) >= .02:
                core.command('af-command', 'ddm_gain', 'volume', f'{gain:.3f}dB', 'volume')
                self.last_gain = gain
        except (AttributeError, RuntimeError, ValueError, SystemError):
            # Loading, seeking and replacing the audio chain temporarily remove metadata.
            return
