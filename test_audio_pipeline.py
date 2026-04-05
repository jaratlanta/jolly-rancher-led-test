#!/usr/bin/env python3
"""
Audio pipeline test — verifies that audio data flows correctly
from input to visualizer render functions.

This test catches the bug where AudioEngine.tick() was gated on
audio_on (pattern mode only), blocking beat_push from updating
when in waveform/visualizer audio mode.

Run: python test_audio_pipeline.py
"""
import sys
sys.path.insert(0, '.')

from ledtest.audio_fx import AudioEngine


def test_audio_tick_runs_when_enabled():
    """tick() must process audio when enabled, regardless of audio_on."""
    engine = AudioEngine()
    engine.enabled = True  # mic is on
    engine.audio_on = False  # NOT in pattern audio mode

    # Simulate audio data
    engine.update_audio(0.8, 0.5, 0.3)
    engine.on_beat(120)

    # tick should process even though audio_on is False
    engine.tick(0.033)

    assert engine.bass_smooth > 0, f"FAIL: bass_smooth={engine.bass_smooth}, expected > 0"
    assert engine.beat_push > 0, f"FAIL: beat_push={engine.beat_push}, expected > 0"
    print("✓ tick() runs when enabled (even without audio_on)")


def test_beat_push_advances_on_beat():
    """beat_push must step forward when beats are detected."""
    engine = AudioEngine()
    engine.enabled = True
    engine.on_beat(120)

    # Simulate several ticks
    for _ in range(10):
        engine.tick(0.033)

    initial_push = engine.beat_push
    assert initial_push > 0, f"FAIL: beat_push={initial_push} after beats"

    # Simulate more beats
    engine.on_beat(120)
    for _ in range(30):
        engine.tick(0.033)

    assert engine.beat_push > initial_push, \
        f"FAIL: beat_push didn't advance ({engine.beat_push} <= {initial_push})"
    print(f"✓ beat_push advances: {initial_push:.2f} → {engine.beat_push:.2f}")


def test_bass_smooth_responds_to_input():
    """bass_smooth must track bass input value."""
    engine = AudioEngine()
    engine.enabled = True
    engine.update_audio(0.9, 0.0, 0.0)

    for _ in range(20):
        engine.tick(0.033)

    assert engine.bass_smooth > 0.5, \
        f"FAIL: bass_smooth={engine.bass_smooth:.3f}, expected > 0.5"
    print(f"✓ bass_smooth tracks input: {engine.bass_smooth:.3f}")


def test_beat_push_accessible_in_waveform_mode():
    """Simulates the exact waveform audio code path from web_engine."""
    engine = AudioEngine()
    engine.enabled = True
    engine.audio_on = False  # waveform mode does NOT set audio_on

    # Simulate browser sending audio data
    engine.update_audio(0.7, 0.4, 0.2)
    engine.on_beat(120)

    # Simulate frame loop calling tick
    for _ in range(15):
        engine.tick(0.033)

    # These are what the waveform renderer reads:
    bass = engine.bass_smooth
    beat_push = engine.beat_push

    assert bass > 0.3, f"FAIL: bass_smooth={bass:.3f} (should be > 0.3)"
    assert beat_push > 0, f"FAIL: beat_push={beat_push:.3f} (should be > 0)"
    print(f"✓ Waveform audio path works: bass={bass:.3f}, beat_push={beat_push:.3f}")


def main():
    print("=== Audio Pipeline Tests ===\n")
    tests = [
        test_audio_tick_runs_when_enabled,
        test_beat_push_advances_on_beat,
        test_bass_smooth_responds_to_input,
        test_beat_push_accessible_in_waveform_mode,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {e}")
        except Exception as e:
            print(f"✗ {test.__name__}: {e}")

    print(f"\n{passed}/{len(tests)} tests passed")
    if passed < len(tests):
        sys.exit(1)
    print("All audio pipeline tests PASS ✓")


if __name__ == "__main__":
    main()
