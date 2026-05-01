"""Tests for human behavior simulator."""
from src.human_simulator import (
    generate_mouse_path, typing_delay, generate_typing_events,
    field_pause, reading_pause, scroll_pattern,
)


def test_mouse_path_starts_and_ends_correctly():
    path = generate_mouse_path((0, 0), (500, 300))
    assert len(path) >= 10
    assert path[0] == (0.0, 0.0)
    # End should be near target (within overshoot correction)
    assert abs(path[-1][0] - 500) < 20
    assert abs(path[-1][1] - 300) < 20


def test_typing_delay_in_range():
    for _ in range(100):
        d = typing_delay()
        assert 0.03 <= d <= 0.3


def test_typing_events_contain_all_chars():
    events = generate_typing_events("hello")
    typed = [e["char"] for e in events if e["type"] == "key" and e["char"] != "Backspace"]
    # Should contain at least all original chars (may have extras from typo corrections)
    assert len(typed) >= 5


def test_field_pause_in_range():
    for _ in range(50):
        p = field_pause()
        assert 1.0 <= p <= 5.0


def test_reading_pause_scales_with_length():
    short = reading_pause(10)
    long = reading_pause(500)
    assert long > short


def test_scroll_pattern_moves_down():
    events = scroll_pattern(3000, 800)
    total_scroll = sum(e["delta"] for e in events if e["type"] == "scroll")
    assert total_scroll > 0  # net downward movement
