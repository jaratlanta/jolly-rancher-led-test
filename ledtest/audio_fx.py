"""
Audio engine: captures frequency band data from browser and provides
smoothed bass/mid/treble values for per-pattern audio functions.

Audio is a toggle (on/off). When on, each pattern uses its own audio_fn
instead of its default fn. No generic modes — audio behavior is bespoke
per pattern.
"""
import math


# Simple on/off for UI
AUDIO_MODES = [
    {"key": "none",  "name": "Off"},
    {"key": "audio", "name": "Audio"},
]


class AudioEngine:
    """Manages audio state: smoothed frequency bands and peak detection."""

    def __init__(self):
        self.enabled = False    # Whether mic capture is active
        self.audio_on = False   # Whether audio mode is engaged
        self.sensitivity = 1.0  # Multiplier on raw FFT values

        # Raw band values (0..1), updated from browser WebAudio FFT
        self.bass = 0.0
        self.mid = 0.0
        self.treble = 0.0

        # Smoothed values (fast attack, slow decay)
        self.bass_smooth = 0.0
        self.mid_smooth = 0.0
        self.treble_smooth = 0.0

        # Peak detection
        self._bass_prev = 0.0
        self._bass_peak = 0.0

        # Accumulated audio-driven time (only advances with audio energy)
        self.audio_time = 0.0

    def reset(self):
        """Clear all audio state."""
        self.bass = self.mid = self.treble = 0.0
        self.bass_smooth = self.mid_smooth = self.treble_smooth = 0.0
        self._bass_prev = self._bass_peak = 0.0
        self.audio_time = 0.0

    def set_mode(self, mode):
        """Set audio mode: None/'none' = off, 'audio' = on."""
        on = (mode == "audio")
        if on != self.audio_on:
            self.audio_on = on
            if not on:
                self.reset()

    def update_audio(self, bass, mid, treble):
        """Update audio frequency band values from browser FFT."""
        s = self.sensitivity
        self.bass = min(1.0, bass * s)
        self.mid = min(1.0, mid * s)
        self.treble = min(1.0, treble * s)

    def tick(self, dt):
        """Called once per frame. Updates smoothed values."""
        if not self.enabled or not self.audio_on:
            return

        # Smooth: fast attack, slower decay
        for attr, raw in [('bass_smooth', self.bass),
                          ('mid_smooth', self.mid),
                          ('treble_smooth', self.treble)]:
            current = getattr(self, attr)
            if raw > current:
                alpha = min(1.0, dt * 18)  # fast attack
            else:
                alpha = min(1.0, dt * 5)   # slower decay
            setattr(self, attr, current + (raw - current) * alpha)

        # Peak detection for bass
        bass_delta = self.bass - self._bass_prev
        self._bass_prev = self.bass
        if bass_delta > 0.1 and self.bass > 0.25:
            self._bass_peak = min(1.0, self._bass_peak + bass_delta * 3)
        else:
            self._bass_peak *= 0.85

        # Advance audio time — only moves when there's audio energy
        # Much gentler accumulation — bass is primary driver
        energy = self.bass_smooth * 0.7 + self.mid_smooth * 0.2 + self.treble_smooth * 0.1
        self.audio_time += energy * dt * 1.5

    def is_active(self):
        """Return True if audio mode is engaged and enabled."""
        return self.enabled and self.audio_on

    def get_state(self):
        """Return state dict for UI sync."""
        return {
            "audio_mode": "audio" if self.audio_on else "none",
            "audio_enabled": self.enabled,
            "audio_sensitivity": self.sensitivity,
        }
