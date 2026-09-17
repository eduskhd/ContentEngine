"""Audio extraction and transcription with word-level timestamps.

Optimizations:
- WhisperModel is kept as a module-level singleton (avoids reloading between jobs).
- Word-level data is cached in videos.words_json (survives server restarts).
- Audio is extracted once to 16kHz mono WAV and reused for all downstream steps.

Backend priority:
1. HuggingFace WhisperForConditionalGeneration (torch-based, no av/tiktoken DLLs)
2. faster-whisper (ctranslate2-based, faster but needs av/ctranslate2)
3. openai-whisper (legacy fallback, needs tiktoken)
"""
import re
import subprocess
import os
from pathlib import Path

from engine.config import CONFIG
from engine import database as db

# ── Singletons ────────────────────────────────────────────────────────────────
_WHISPER_MODEL = None   # faster-whisper
_HF_PROCESSOR = None    # transformers WhisperProcessor
_HF_MODEL = None        # transformers WhisperForConditionalGeneration

_HF_MODEL_MAP = {
    "tiny":   "openai/whisper-tiny",
    "base":   "openai/whisper-base",
    "small":  "openai/whisper-small",
    "medium": "openai/whisper-medium",
    "large":  "openai/whisper-large-v3",
}


def _get_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        from faster_whisper import WhisperModel
        _WHISPER_MODEL = WhisperModel(CONFIG.whisper_model, device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def _get_hf_model():
    global _HF_PROCESSOR, _HF_MODEL
    if _HF_MODEL is None:
        from transformers import WhisperProcessor, WhisperForConditionalGeneration
        import torch
        model_name = _HF_MODEL_MAP.get(CONFIG.whisper_model, "openai/whisper-small")
        _HF_PROCESSOR = WhisperProcessor.from_pretrained(model_name)
        _HF_MODEL = WhisperForConditionalGeneration.from_pretrained(
            model_name, torch_dtype=torch.float32
        )
        _HF_MODEL.eval()
    return _HF_PROCESSOR, _HF_MODEL


def _has_audio_stream(video_path: str) -> bool:
    cmd = [CONFIG.ffprobe_path, "-v", "quiet", "-select_streams", "a",
           "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0 and "audio" in result.stdout


def transcribe(job_id: str, video_id: str, video_path: str) -> list[dict]:
    """
    Transcribe video audio with word-level timestamps.

    Cache strategy:
    1. Check video_id cache (same-job retry path).
    2. Check path-based cache (same source processed before).
    3. Otherwise: extract audio → run Whisper → persist words_json.
    """
    # ── 1. Check transcript cache (video_id) ──────────────────────────────────
    cached = db.get_cached_words(video_id)
    if cached is not None:
        return cached

    # ── 2. Check path-based cache (same file processed in a different job) ────
    cached_by_path = db.get_cached_words_by_path(video_path)
    if cached_by_path is not None:
        db.save_words_cache(video_id, cached_by_path)
        db.update_job(job_id, status="TRANSCRIBING")
        return cached_by_path

    if not _has_audio_stream(video_path):
        db.update_video(video_id, transcript="", audio_path=None, words_json="[]")
        db.update_job(job_id, status="TRANSCRIBING")
        return []

    # ── 2. Extract audio (once) ───────────────────────────────────────────────
    audio_path = _extract_audio(video_path, video_id)
    db.update_video(video_id, audio_path=audio_path)

    # ── 3. Transcribe ─────────────────────────────────────────────────────────
    segments = _run_whisper(audio_path)
    words = _flatten_to_words(segments)

    transcript_text = " ".join(s.get("text", "").strip() for s in segments)
    db.update_video(video_id, transcript=transcript_text)
    db.update_job(job_id, status="TRANSCRIBING")

    # ── 4. Cache words for reuse ──────────────────────────────────────────────
    db.save_words_cache(video_id, words)

    return words


def _extract_audio(video_path: str, video_id: str = None) -> str:
    """Extract audio to 16kHz mono WAV. Reuses existing file if present."""
    out_dir = Path(CONFIG.output_dir) / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    audio_path = str(out_dir / f"{stem}_audio.wav")

    if Path(audio_path).exists():
        return audio_path

    cmd = [
        CONFIG.ffmpeg_path, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        stderr_lines = result.stderr.decode(errors="replace").splitlines()
        error_lines = [l for l in stderr_lines
                       if not l.startswith((" ", "\t", "ffmpeg version", "built with",
                                            "configuration", "lib", "Copyright"))]
        raise RuntimeError(f"Audio extraction failed: {chr(10).join(error_lines[-10:])}")
    return audio_path


def _run_whisper(audio_path: str) -> list[dict]:
    try:
        return _run_hf_whisper(audio_path)
    except Exception:
        try:
            return _run_faster_whisper(audio_path)
        except Exception:
            return _run_openai_whisper(audio_path)


def _run_hf_whisper(audio_path: str) -> list[dict]:
    """HuggingFace Whisper — uses torch only, no av/tiktoken DLLs required."""
    import soundfile as sf
    import torch
    import numpy as np

    processor, model = _get_hf_model()

    audio, sr = sf.read(audio_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Resample to 16 kHz if needed
    if sr != 16000:
        import librosa
        audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
        sr = 16000

    TARGET_SR = 16000
    CHUNK_S = 30
    chunk_samples = CHUNK_S * TARGET_SR

    all_segments: list[dict] = []
    offset = 0

    while offset < len(audio):
        chunk_end = min(offset + chunk_samples, len(audio))
        chunk = audio[offset:chunk_end].copy()
        time_offset = offset / TARGET_SR

        # Pad short final chunk to 30 s so the model always gets a full context window
        if len(chunk) < chunk_samples:
            chunk = np.pad(chunk, (0, chunk_samples - len(chunk)))

        inputs = processor(chunk, sampling_rate=TARGET_SR, return_tensors="pt")

        with torch.no_grad():
            generated = model.generate(
                **inputs,
                return_timestamps=True,
                task="transcribe",
            )

        decoded = processor.batch_decode(generated, skip_special_tokens=False)
        raw_text = decoded[0] if decoded else ""

        segs = _parse_whisper_timestamp_tokens(raw_text, time_offset)
        all_segments.extend(segs)

        offset = chunk_end

    return all_segments


def _parse_whisper_timestamp_tokens(raw: str, time_offset: float) -> list[dict]:
    """
    Parse Whisper timestamp tokens of the form <|0.00|>text<|1.20|>.
    Returns a list of segment dicts with interpolated word timestamps.
    """
    # Match timestamp token value
    ts_pattern = re.compile(r"<\|([\d.]+)\|>")
    parts = ts_pattern.split(raw)

    # parts alternates: [pre-text, ts1, text1, ts2, text2, ts3, ...]
    segments = []
    i = 0
    while i < len(parts) - 2:
        try:
            t_start = float(parts[i]) + time_offset
            text = parts[i + 1].strip()
            t_end = float(parts[i + 2]) + time_offset
        except (ValueError, IndexError):
            i += 1
            continue

        # Skip empty or pure-noise segments
        if not text or t_end <= t_start:
            i += 2
            continue

        words_raw = [w for w in text.split() if w]
        if not words_raw:
            i += 2
            continue

        n = len(words_raw)
        word_dur = (t_end - t_start) / n
        seg_words = [
            {
                "word": words_raw[j],
                "start": round(t_start + j * word_dur, 3),
                "end": round(t_start + (j + 1) * word_dur, 3),
                "probability": 1.0,
            }
            for j in range(n)
        ]
        segments.append({
            "text": text,
            "start": t_start,
            "end": t_end,
            "words": seg_words,
        })
        i += 2

    return segments


def _run_faster_whisper(audio_path: str) -> list[dict]:
    model = _get_model()
    try:
        segments_gen, _ = model.transcribe(
            audio_path,
            word_timestamps=True,
            vad_filter=True,
        )
    except TypeError:
        segments_gen, _ = model.transcribe(audio_path, word_timestamps=True)
    segments = []
    for seg in segments_gen:
        words = [
            {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
            for w in (seg.words or [])
        ]
        segments.append({
            "text": seg.text,
            "start": seg.start,
            "end": seg.end,
            "words": words,
        })
    return segments


def _run_openai_whisper(audio_path: str) -> list[dict]:
    import whisper
    import soundfile as sf
    data, sr = sf.read(audio_path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=16000)
    model = whisper.load_model(CONFIG.whisper_model)
    result = model.transcribe(data, word_timestamps=True, language="en")
    return result.get("segments", [])


def _flatten_to_words(segments: list[dict]) -> list[dict]:
    words = []
    for seg in segments:
        seg_words = seg.get("words", [])
        if seg_words:
            for w in seg_words:
                words.append({
                    "word": w.get("word", "").strip(),
                    "start": w.get("start", seg.get("start", 0)),
                    "end": w.get("end", seg.get("end", 0)),
                    "probability": w.get("probability", 1.0),
                    "segment_text": seg.get("text", "").strip(),
                })
        else:
            words.append({
                "word": seg.get("text", "").strip(),
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "probability": 1.0,
                "segment_text": seg.get("text", "").strip(),
            })
    return words
