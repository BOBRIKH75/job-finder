"""Human behavior simulator — realistic mouse, typing, scrolling, pauses."""
import math, random, time


def bezier_point(t: float, p0: tuple, p1: tuple, p2: tuple, p3: tuple) -> tuple:
    """Cubic Bezier curve point at parameter t."""
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
    )


def generate_mouse_path(start: tuple, end: tuple, steps: int = 20) -> list[tuple]:
    """Generate human-like mouse path using Bezier curves with overshoot."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    # Random control points for natural curve
    cp1 = (start[0] + dx * 0.3 + random.uniform(-30, 30), start[1] + dy * 0.1 + random.uniform(-30, 30))
    cp2 = (start[0] + dx * 0.7 + random.uniform(-20, 20), start[1] + dy * 0.9 + random.uniform(-20, 20))
    # 18% chance of overshoot (research: humans overshoot 15-22%)
    if random.random() < 0.18:
        overshoot = (end[0] + random.uniform(3, 12), end[1] + random.uniform(3, 12))
        path = [bezier_point(t / steps, start, cp1, cp2, overshoot) for t in range(steps)]
        # Correction back to target
        path += [bezier_point(t / 5, overshoot, end, end, end) for t in range(6)]
    else:
        path = [bezier_point(t / steps, start, cp1, cp2, end) for t in range(steps + 1)]
    return [(round(x, 1), round(y, 1)) for x, y in path]


def typing_delay() -> float:
    """Human-like inter-key delay (50-300ms, log-normal distribution)."""
    delay = random.lognormvariate(math.log(0.1), 0.4)
    return max(0.03, min(0.3, delay))


def generate_typing_events(text: str) -> list[dict]:
    """Generate realistic typing events with occasional typos and corrections."""
    events = []
    for i, char in enumerate(text):
        # 3% typo rate (research: humans 2-5%)
        if random.random() < 0.03 and char.isalpha():
            wrong = chr(ord(char) + random.choice([-1, 1]))
            events.append({"type": "key", "char": wrong, "delay": typing_delay()})
            events.append({"type": "key", "char": "Backspace", "delay": random.uniform(0.1, 0.3)})
        events.append({"type": "key", "char": char, "delay": typing_delay()})
        # Occasional thinking pause between words
        if char == " " and random.random() < 0.15:
            events.append({"type": "pause", "delay": random.uniform(0.3, 1.2)})
    return events


def field_pause() -> float:
    """Pause between form fields (1-5 seconds, research data)."""
    return random.uniform(1.0, 5.0)


def reading_pause(word_count: int) -> float:
    """Time to read text (200-250 WPM scanning speed)."""
    wpm = random.uniform(200, 250)
    return max(1.0, (word_count / wpm) * 60)


def scroll_pattern(page_height: int, viewport_height: int) -> list[dict]:
    """Generate human-like scroll events."""
    events = []
    pos = 0
    while pos < page_height - viewport_height:
        delta = random.randint(100, 400)
        events.append({"type": "scroll", "delta": delta, "delay": random.uniform(0.5, 2.0)})
        pos += delta
        # 25% chance of pause to read (research: 20-30% scroll-back)
        if random.random() < 0.25:
            events.append({"type": "pause", "delay": random.uniform(1.0, 4.0)})
        # 10% chance of scroll back up
        if random.random() < 0.10 and pos > 300:
            back = random.randint(50, 200)
            events.append({"type": "scroll", "delta": -back, "delay": random.uniform(0.3, 1.0)})
    return events
