"""Audio energy and pace analysis per candidate window."""
import numpy as np

from engine.config import CONFIG
from engine import database as db

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False


def analyze_audio(job_id: str, audio_path: str, candidates: list[dict]) -> dict[str, float]:
    """Returns {candidate_id: audio_score}."""
    if not LIBROSA_AVAILABLE or not audio_path:
        return {c["id"]: 0.5 for c in candidates}

    try:
        y, sr = librosa.load(audio_path, sr=16000, mono=True)
    except Exception:
        return {c["id"]: 0.5 for c in candidates}

    scores = {}
    for cand in candidates:
        try:
            score = _score_window(y, sr, cand["start_s"], cand["end_s"])
            db.update_candidate(cand["id"], audio_score=score)
            scores[cand["id"]] = score
        except Exception:
            scores[cand["id"]] = 0.5
    return scores


def _score_window(y: np.ndarray, sr: int, start: float, end: float) -> float:
    start_sample = int(start * sr)
    end_sample = int(end * sr)
    segment = y[start_sample:end_sample]

    if len(segment) == 0:
        return 0.5

    rms = librosa.feature.rms(y=segment, frame_length=2048, hop_length=512)[0]
    avg_rms = float(np.mean(rms))
    peak_rms = float(np.max(rms))

    # Normalize RMS to 0-1 (typical speech RMS ~0.05-0.15)
    energy_score = min(1.0, avg_rms / 0.1)

    # Dynamic range: ratio of peak to mean (higher = more engaging)
    if avg_rms > 0:
        dynamic = min(1.0, (peak_rms / avg_rms - 1.0) / 2.0)
    else:
        dynamic = 0.0

    # Silence ratio (penalize long silences)
    silence_threshold = avg_rms * 0.1
    silence_ratio = float(np.mean(rms < silence_threshold))
    silence_penalty = max(0.0, 1.0 - silence_ratio * 2)

    return min(1.0, energy_score * 0.5 + dynamic * 0.3 + silence_penalty * 0.2)
