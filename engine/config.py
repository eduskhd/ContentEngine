import os
from dataclasses import dataclass, field

FFMPEG_PATH = r"C:\Users\edupo\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
FFPROBE_PATH = r"C:\Users\edupo\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffprobe.exe"


@dataclass
class ScoringWeights:
    semantic_potential: float = 0.20
    hook: float = 0.20
    visual_interest: float = 0.15
    audio_energy: float = 0.10
    context_independence: float = 0.15
    pace: float = 0.10
    surprise_emotion: float = 0.10


@dataclass
class ViralityEnsembleWeights:
    virality_predictor: float = 0.30
    hook: float = 0.20
    semantic: float = 0.15
    visual: float = 0.10
    audio: float = 0.05
    context: float = 0.10
    platform_fit: float = 0.10


@dataclass
class PrePublishThresholds:
    publish_min: float = 50.0   # score >= 50 → PUBLISH (ready to post)
    review_min: float = 25.0    # score >= 25 → REVIEW (manual check needed)


@dataclass
class EngineConfig:
    scoring_weights: ScoringWeights = field(default_factory=ScoringWeights)
    virality_ensemble: ViralityEnsembleWeights = field(default_factory=ViralityEnsembleWeights)
    prepublish: PrePublishThresholds = field(default_factory=PrePublishThresholds)
    target_clips: int = 5
    finalist_multiplier: int = 3
    max_render_retries: int = 3
    exploration_ratio: float = 0.10
    min_clip_duration: float = 15.0
    max_clip_duration: float = 60.0
    target_resolution: tuple = (1080, 1920)
    target_fps: int = 30
    mode: str = "REVIEW"
    # Enhanced analysis settings
    min_virality_for_auto: float = 70.0
    target_series_part_duration: float = 30.0
    max_series_parts: int = 4
    min_series_total_duration: float = 60.0
    generate_series: bool = True
    deduplicate_iou_threshold: float = 0.5
    smart_cut_window: float = 12.0
    skills_dir: str = r"C:\Users\edupo\.claude\skills"
    output_dir: str = r"C:\Users\edupo\Desktop\ContentEngine\output"
    db_path: str = r"C:\Users\edupo\Desktop\ContentEngine\db\engine.sqlite"
    ffmpeg_path: str = FFMPEG_PATH
    ffprobe_path: str = FFPROBE_PATH
    whisper_model: str = "base"


CONFIG = EngineConfig()
