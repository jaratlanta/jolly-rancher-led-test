"""
Audio engine — predictive metronome with BPM mode.

Three modes:
  none  — no audio, patterns animate on their own timer
  audio — beat-synced time + bass/mid/treble frequency data drive patterns
  bpm   — pure metronome: only beat_count and beat_phase drive patterns

KEY DESIGN: Once a BPM is established, the engine runs a FREE-RUNNING
METRONOME that auto-increments beat_count on schedule. Browser beat
detections only nudge the BPM and fine-tune phase — they never directly
trigger visual beats. This eliminates jitter from sloppy beat detection.
"""
import math
import time


AUDIO_MODES = [
    {"key": "none",  "name": "Off"},
    {"key": "audio", "name": "Audio"},
    {"key": "bpm",   "name": "BPM"},
]


class AudioEngine:
    """Free-running metronome with BPM tracking."""

    def __init__(self):
        self.enabled = False
        self._mode = "none"
        self.audio_on = False
        self.sensitivity = 1.0

        # Raw band values (0..1)
        self.bass = 0.0
        self.mid = 0.0
        self.treble = 0.0

        # Smoothed values
        self.bass_smooth = 0.0
        self.mid_smooth = 0.0
        self.treble_smooth = 0.0

        # BPM tracking
        self._bpm = 0.0              # smoothed raw BPM from browser
        self._effective_bpm = 0.0    # actual animation BPM (halved in BPM mode)
        self._beat_interval = 0.0    # seconds per visual beat

        # Free-running metronome state
        self._metro_time = 0.0       # accumulated time within current beat
        self._beat_count = 0         # auto-incremented by metronome
        self._beat_phase = 0.0       # 0.0 = on beat, 1.0 = just before next

        # Animation time (used by "audio" mode)
        self.audio_time = 0.0
        self._step_per_beat = 0.4

    def reset(self):
        self.bass = self.mid = self.treble = 0.0
        self.bass_smooth = self.mid_smooth = self.treble_smooth = 0.0
        self._bpm = 0.0
        self._effective_bpm = 0.0
        self._beat_interval = 0.0
        self._metro_time = 0.0
        self._beat_count = 0
        self._beat_phase = 0.0
        self.audio_time = 0.0

    def set_mode(self, mode):
        if mode not in ("none", "audio", "bpm"):
            mode = "none"
        if mode != self._mode:
            self._mode = mode
            self.audio_on = mode in ("audio", "bpm")
            if mode == "none":
                self.reset()

    @property
    def beat_count(self):
        return self._beat_count

    @property
    def beat_phase(self):
        return self._beat_phase

    def update_audio(self, bass, mid, treble):
        s = self.sensitivity
        self.bass = min(1.0, bass * s)
        self.mid = min(1.0, mid * s)
        self.treble = min(1.0, treble * s)

    def on_beat(self, bpm):
        """Called when browser detects a beat.

        This ONLY updates the BPM estimate. It does NOT directly trigger
        visual beats — the free-running metronome in tick() handles that.
        The metronome's phase is gently nudged toward the detected beat.
        """
        if not self.enabled or not self.audio_on:
            return

        # Update BPM (smooth heavily to avoid jitter)
        if bpm > 0:
            if self._bpm > 0:
                self._bpm = self._bpm * 0.8 + bpm * 0.2
            else:
                self._bpm = bpm

            # Halve rate in BPM mode (120→60 visual BPM)
            if self._mode == "bpm":
                self._effective_bpm = self._bpm / 2.0
            else:
                self._effective_bpm = self._bpm
            self._beat_interval = 60.0 / max(20, self._effective_bpm)

        # Phase nudge: gently pull metronome toward the detected beat
        # Don't hard-reset — just adjust slightly so we drift into alignment
        if self._beat_interval > 0:
            # If we're more than 70% through the beat, the detected beat
            # is probably for the NEXT beat — nudge forward
            if self._beat_phase > 0.7:
                self._metro_time = self._beat_interval * 0.95
            # If we're early in the beat, the detection is late — nudge back
            elif self._beat_phase > 0.1:
                self._metro_time *= 0.85  # pull back gently

    def tick(self, dt):
        if not self.enabled or not self.audio_on:
            return

        # Smooth band values
        for attr, raw in [('bass_smooth', self.bass),
                          ('mid_smooth', self.mid),
                          ('treble_smooth', self.treble)]:
            current = getattr(self, attr)
            if raw > current:
                alpha = min(1.0, dt * 18)
            else:
                alpha = min(1.0, dt * 5)
            setattr(self, attr, current + (raw - current) * alpha)

        # ── Free-running metronome ─────────────────────────────────────
        if self._beat_interval > 0:
            self._metro_time += dt

            # When we've accumulated a full beat interval, advance beat_count
            while self._metro_time >= self._beat_interval:
                self._metro_time -= self._beat_interval
                self._beat_count += 1

            # Phase: 0.0 = just hit a beat, 1.0 = about to hit next
            self._beat_phase = self._metro_time / self._beat_interval

            # ── Audio mode: advance audio_time with pulse shape ────────
            if self._mode == "audio":
                phase = self._beat_phase
                base_speed = 0.3
                boost = 1.7
                pulse = (math.cos(phase * 2.0 * math.pi) + 1.0) / 2.0
                speed = base_speed + boost * pulse
                self.audio_time += speed * self._step_per_beat * dt / self._beat_interval
        else:
            # No BPM yet — gentle drift based on audio energy
            energy = self.bass_smooth * 0.5 + self.mid_smooth * 0.3 + self.treble_smooth * 0.2
            if energy > 0.05:
                self.audio_time += energy * dt * 0.2

        # Fade BPM if no audio data for a while
        # (bass_smooth will decay to 0 when music stops)
        if self._bpm > 0 and self.bass_smooth < 0.01 and self.mid_smooth < 0.01:
            self._bpm *= 0.998  # very slow fade
            if self._bpm < 30:
                self._bpm = 0.0
                self._effective_bpm = 0.0
                self._beat_interval = 0.0

    def is_active(self):
        return self.enabled and self.audio_on

    def is_bpm_mode(self):
        return self.enabled and self._mode == "bpm"

    def is_audio_mode(self):
        return self.enabled and self._mode == "audio"

    def get_state(self):
        return {
            "audio_mode": self._mode,
            "audio_enabled": self.enabled,
            "audio_sensitivity": self.sensitivity,
            "bpm": round(self._effective_bpm) if self._effective_bpm > 0 else 0,
        }
