"""
Caption renderer: ASS subtitle generation + ffmpeg burn-in.

Supports word-level highlight (karaoke-style) with presets,
multiple animations, and safe-zone positioning.
"""
import os
import shutil
import subprocess
import tempfile

from engine.config import CONFIG
from engine.captions.extractor import group_words


# ── Color helpers ──────────────────────────────────────────────────────────────

def _hex_to_ass(hex_color: str, alpha: int = 0) -> str:
    """Convert #RRGGBB to ASS &HAABBGGRR (note: inverted alpha, BGR order)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ass_time(seconds: float) -> str:
    """Format seconds as ASS H:MM:SS.cc"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ── Position → ASS alignment + margin ─────────────────────────────────────────

def _position_ass(position: str, margin_v: int) -> tuple[int, int]:
    """Return (ASS alignment, MarginV).
    Alignment codes: 2=bottom-center, 5=mid-center, 8=top-center
    """
    if position == "top":
        return 8, margin_v
    if position == "center":
        return 5, 0
    return 2, margin_v   # lower_third and bottom both use bottom-center


# ── ASS script builder ─────────────────────────────────────────────────────────

def build_ass(
    words: list[dict],
    settings: dict,
    width: int = 1080,
    height: int = 1920,
) -> str:
    """
    Build a complete ASS subtitle file with word-level highlighting.

    Each word in a group gets its own timed event showing the full group,
    with that word in highlight color + optional scale effect (karaoke style).
    """
    if not words:
        return _empty_ass(width, height)

    max_words = int(settings.get("max_words", 4))
    uppercase  = settings.get("uppercase", True)
    animation  = settings.get("animation", "pop")
    position   = settings.get("position", "lower_third")
    margin_v   = int(settings.get("margin_v", 200))
    margin_h   = int(settings.get("margin_h", 60))

    text_color      = _hex_to_ass(settings.get("text_color", "#FFFFFF"))
    highlight_color = _hex_to_ass(settings.get("highlight_color", "#FFFF00"))
    stroke_color    = _hex_to_ass(settings.get("stroke_color", "#000000"))
    stroke_w        = float(settings.get("stroke_width", 3))
    shadow          = 1 if settings.get("shadow", True) else 0
    glow            = settings.get("glow", False)
    glow_color      = _hex_to_ass(settings.get("glow_color", settings.get("highlight_color", "#FFFF00")))

    font_family = settings.get("font_family", "Arial")
    font_size   = int(settings.get("font_size", 38))
    bold        = 1 if settings.get("bold", True) else 0

    alignment, ass_margin_v = _position_ass(position, margin_v)

    # Scale font to video resolution (baseline: 1080×1920)
    scale = min(width / 1080, height / 1920)
    scaled_font = max(14, int(font_size * scale))

    groups = group_words(words, max_words)

    # ── Script Info ────────────────────────────────────────────────────────────
    out = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "Timer: 100.0000",
        "",
    ]

    # ── Styles ─────────────────────────────────────────────────────────────────
    out += [
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        (
            f"Style: Default,{font_family},{scaled_font},"
            f"{text_color},&H000000FF,{stroke_color},&H00000000,"
            f"{bold},0,0,0,100,100,0,0,1,{stroke_w:.1f},{shadow},"
            f"{alignment},{margin_h},{margin_h},{ass_margin_v},1"
        ),
        "",
    ]

    # ── Events ─────────────────────────────────────────────────────────────────
    out += [
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for group in groups:
        gwords = group["words"]
        if not gwords:
            continue

        for wi, active_w in enumerate(gwords):
            ev_start = active_w["start"]
            ev_end   = (gwords[wi + 1]["start"] if wi + 1 < len(gwords)
                        else group["end"])
            if ev_end <= ev_start:
                ev_end = ev_start + 0.04

            # Build text with override tags for the active word
            parts = []
            for j, w in enumerate(gwords):
                display = w["word"].upper() if uppercase else w["word"]
                if j == wi:
                    if animation in ("pop", "scale", "bounce"):
                        scale_pct = 115 if animation == "bounce" else 110
                        parts.append(
                            f"{{\\c{highlight_color}\\fscx{scale_pct}\\fscy{scale_pct}}}"
                            f"{display}{{\\r}}"
                        )
                    else:
                        parts.append(f"{{\\c{highlight_color}}}{display}{{\\r}}")
                else:
                    parts.append(display)

            text = " ".join(parts)

            # Event-level animation tags
            prefix = ""
            if animation == "fade":
                dur_ms = int((ev_end - ev_start) * 1000)
                fi = min(120, int(dur_ms * 0.25))
                fo = min(80,  int(dur_ms * 0.15))
                prefix = f"{{\\fad({fi},{fo})}}"
            elif glow and wi == 0:
                # Add glow on first word of each group via blur
                prefix = f"{{\\blur2}}"

            out.append(
                f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},"
                f"Default,,0,0,0,,{prefix}{text}"
            )

    return "\n".join(out) + "\n"


def _empty_ass(width: int, height: int) -> str:
    return (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n[Events]\n"
    )


# ── ffmpeg burn-in ─────────────────────────────────────────────────────────────

def burn_captions_ass(
    input_path: str,
    output_path: str,
    words: list[dict],
    settings: dict,
    width: int = 1080,
    height: int = 1920,
) -> bool:
    """
    Burn ASS captions into video. Returns True on success.
    Falls back to copying the source if no words are available.
    """
    if not words or not settings.get("enabled", True):
        shutil.copy2(input_path, output_path)
        return True

    ass_content = build_ass(words, settings, width, height)

    tmp = tempfile.NamedTemporaryFile(
        suffix=".ass", mode="w", delete=False, encoding="utf-8"
    )
    tmp.write(ass_content)
    tmp.close()
    ass_path = tmp.name

    try:
        safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
        cmd = [
            CONFIG.ffmpeg_path, "-y",
            "-i", input_path,
            "-vf", f"ass='{safe_ass}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return result.returncode == 0
    finally:
        try:
            os.unlink(ass_path)
        except OSError:
            pass
