"""
Caption preset definitions.
Add new presets here — no other file needs to change.
"""

_PRESETS: dict[str, dict] = {
    "impact": {
        "font_family": "Arial",
        "font_size": 38,
        "bold": True,
        "text_color": "#FFFFFF",
        "highlight_color": "#FFFF00",
        "stroke_color": "#000000",
        "stroke_width": 3,
        "shadow": True,
        "glow": False,
        "glow_color": "#FFFF00",
        "position": "lower_third",
        "max_words": 4,
        "animation": "pop",
        "uppercase": True,
        "margin_v": 200,
        "margin_h": 60,
        "background": False,
        "background_color": "#80000000",
        "line_spacing": 1.2,
    },
    "aura": {
        "font_family": "Arial",
        "font_size": 34,
        "bold": True,
        "text_color": "#FFFFFF",
        "highlight_color": "#00D4FF",
        "stroke_color": "#000000",
        "stroke_width": 2,
        "shadow": True,
        "glow": True,
        "glow_color": "#00D4FF",
        "position": "lower_third",
        "max_words": 4,
        "animation": "fade",
        "uppercase": True,
        "margin_v": 200,
        "margin_h": 60,
        "background": False,
        "background_color": "#60000000",
        "line_spacing": 1.2,
    },
    "glowing_bold": {
        "font_family": "Arial",
        "font_size": 42,
        "bold": True,
        "text_color": "#FFFFFF",
        "highlight_color": "#FF6B00",
        "stroke_color": "#000000",
        "stroke_width": 4,
        "shadow": True,
        "glow": True,
        "glow_color": "#FF6B00",
        "position": "lower_third",
        "max_words": 3,
        "animation": "scale",
        "uppercase": True,
        "margin_v": 200,
        "margin_h": 60,
        "background": False,
        "background_color": "#60000000",
        "line_spacing": 1.2,
    },
}


def get_preset(name: str) -> dict:
    base = _PRESETS.get(name) or _PRESETS["impact"]
    return {**base, "preset": name, "enabled": True}


def list_presets() -> list[str]:
    return list(_PRESETS.keys())


def default_settings() -> dict:
    return get_preset("impact")


def apply_overrides(base: dict, overrides: dict) -> dict:
    result = {**base}
    for k, v in overrides.items():
        if v is not None:
            result[k] = v
    return result
