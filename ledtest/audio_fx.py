"""
Audio engine — predictive beat-sync with downbeat pulse.

Once the browser detects BPM, this engine runs an internal metronome that
PREDICTS when beats will land (eliminating latency). The animation advances
with a cosine pulse shape: fast burst on the downbeat, smooth glide between.

The browser's beat detection only updates the BPM and re-syncs the phase —
the actual animation timing is driven by the predicted beat clock.
"""
import math
import time


AUDIO_MODES = [
    {"key": "none",  "name": "Off"},
    {"key": "audio", "name": "Audio"},
]


class AudioEngine:
    """Predictive beat-synced animation driver."""

    def __init__(self):
        self.enabled = False
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

        # BPM and beat clock
        self._bpm = 0.0
        self._beat_interval = 0.0     # seconds per beat
        self._last_beat_time = 0.0    # monotonic time of last confirmed beat
        self._beat_count = 0          # total beats received (for sync)
        self._time_since_beat = 0.0   # seconds since last browser beat event

        # Animation time — advances with pulse shape
        self.audio_time = 0.0
        self._step_per_beat = 0.4     # how much audio_time advances per beat

    def reset(self):
        self.bass = self.mid = self.treble = 0.0
        self.bass_smooth = self.mid_smooth = self.treble_smooth = 0.0
        self._bpm = 0.0
        self._beat_interval = 0.0
        self._last_beat_time = 0.0
        self._beat_count = 0
        self._time_since_beat = 0.0
        self.audio_time = 0.0

    def set_mode(self, mode):
        on = (mode == "audio")
        if on != self.audio_on:
            self.audio_on = on
            if not on:
                self.reset()

    def update_audio(self, bass, mid, treble):
        s = self.sensitivity
        self.bass = min(1.0, bass * s)
        self.mid = min(1.0, mid * s)
        self.treble = min(1.0, treble * s)

    def on_beat(self, bpm):
        """Called by server when browser detects a beat.

        This re-syncs our internal metronome phase to the actual beat,
        and updates the BPM for prediction.
        """
        if not self.enabled or not self.audio_on:
            return

        now = time.monotonic()

        # Update BPM (smooth it to avoid jitter)
        if bpm > 0:
            if self._bpm > 0:
                self._bpm = self._bpm * 0.7 + bpm * 0.3
            else:
                self._bpm = bpm
            self._beat_interval = 60.0 / max(40, self._bpm)

        # Re-sync phase: this beat is "now"
        self._last_beat_time = now
        self._beat_count += 1
        self._time_since_beat = 0.0

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

        self._time_since_beat += dt

        # ── Predictive beat-synced advancement ────────────────────────
        # Once we have a BPM, run an internal metronome.
        # Animation speed pulses: FAST on downbeat, SLOW between beats.
        # This makes the animation visibly "hit" on each beat.

        if self._bpm > 0 and self._beat_interval > 0:
            # Where are we in the current beat cycle? (0.0 = on beat, 1.0 = next beat)
            phase = self._time_since_beat / self._beat_interval
            # Wrap phase (in case we miss a beat event)
            phase = phase % 1.0

            # Pulse shape: cosine curve that peaks at phase=0 (downbeat)
            #   At phase 0.0 (downbeat): speed = base + boost = high
            #   At phase 0.5 (between):  speed = base         = low
            # This creates a smooth acceleration/deceleration per beat.
            base_speed = 0.3   # minimum speed between beats (gentle glide)
            boost = 1.7        # extra speed on the downbeat
            pulse = (math.cos(phase * 2.0 * math.pi) + 1.0) / 2.0  # 0..1, peaks at phase=0

            speed = base_speed + boost * pulse

            # Advance audio_time
            self.audio_time += speed * self._step_per_beat * dt / self._beat_interval

        else:
            # No BPM yet — gentle drift based on audio energy
            energy = self.bass_smooth * 0.5 + self.mid_smooth * 0.3 + self.treble_smooth * 0.2
            if energy > 0.05:
                self.audio_time += energy * dt * 0.2

        # Fade BPM if no beats for a while (music stopped)
        if self._time_since_beat > 5.0:
            self._bpm *= 0.95
            if self._bpm < 30:
                self._bpm = 0.0
                self._beat_interval = 0.0

    def is_active(self):
        return self.enabled and self.audio_on

    def get_state(self):
        return {
            "audio_mode": "audio" if self.audio_on else "none",
            "audio_enabled": self.enabled,
            "audio_sensitivity": self.sensitivity,
            "bpm": round(self._bpm) if self._bpm > 0 else 0,
        }
