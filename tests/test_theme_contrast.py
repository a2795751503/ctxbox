"""WCAG contrast guard: every fg/bg token pair must stay readable.

This test is the permanent lock on the "white-on-white" class of bugs.
"""

from ctxbox.gui.theme import DARK, LIGHT


def _lum(hexc: str) -> float:
    hexc = hexc.lstrip("#")
    r, g, b = (int(hexc[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(fg: str, bg: str) -> float:
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


# (fg_key, bg_key, min_ratio) — 正文 4.5, 弱化文字 3.0
PAIRS = [
    ("text", "bg", 4.5),
    ("text", "card", 4.5),
    ("text", "input_bg", 4.5),
    ("text_secondary", "bg", 4.5),
    ("text_secondary", "card", 4.5),
    ("text_muted", "card", 3.0),
    ("bubble_user_text", "bubble_user_bg", 4.5),
    ("bubble_user_header", "bubble_user_bg", 3.0),
    ("bubble_assistant_text", "bubble_assistant_bg", 4.5),
    ("bubble_tool_text", "bubble_tool_bg", 4.5),
    ("code_text", "code_bg", 4.5),
    ("well_text", "well_bg", 4.5),
    ("well_user_text", "well_user_bg", 4.5),
    ("raw_text", "raw_bg", 4.5),
    ("text", "menu_bg", 4.5),
    ("text", "accent_soft", 4.5),
]

THEMES = {"light": LIGHT, "dark": DARK}


def test_contrast_ratios():
    failures = []
    for name, t in THEMES.items():
        for fg_key, bg_key, min_ratio in PAIRS:
            fg, bg = t[fg_key], t[bg_key]
            ratio = contrast(fg, bg)
            if ratio < min_ratio:
                failures.append(
                    f"{name}: {fg_key}({fg}) on {bg_key}({bg}) = {ratio:.2f} < {min_ratio}"
                )
    assert not failures, "\n".join(failures)


def test_primary_button_contrast():
    for name, t in THEMES.items():
        assert contrast("#ffffff", t["accent"]) >= 4.5, f"{name} primary button"


def test_known_bug_white_on_white():
    """The reported bug: light text on white bubble must be impossible."""
    for _name, t in THEMES.items():
        for key in ("bubble_assistant_text", "bubble_tool_text", "code_text", "text"):
            bg_key = {
                "bubble_assistant_text": "bubble_assistant_bg",
                "bubble_tool_text": "bubble_tool_bg",
                "code_text": "code_bg",
                "text": "card",
            }[key]
            assert contrast(t[key], t[bg_key]) >= 4.5
