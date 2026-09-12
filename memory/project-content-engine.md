---
name: project-content-engine
description: AI Short-Form Content Engine project at C:\Users\edupo\Desktop\ContentEngine — automated pipeline for creating, evaluating, QA-ing, and publishing short-form video clips
metadata:
  type: project
---

# ContentEngine Project

AI-powered automated short-form video pipeline. Built 2026-09-02.

**Location:** `C:\Users\edupo\Desktop\ContentEngine`

**Status:** MVP complete. E2E tested against xanderdoesai.mp4.

## Architecture

21-step pipeline: INGEST → TRANSCRIPTION → CANDIDATE DETECTION → VISUAL ANALYSIS → AUDIO ANALYSIS → PLATFORM FIT → VIRALITY SCORING → SKILLS ADVISORS → CLIP GENERATION → REFRAMING → CAPTIONS → QA → PRE-PUBLISH GATE → (SCHEDULE → PUBLISH → ANALYTICS → LEARNING LOOP)

## Key Files

- `main.py` — CLI entry point
- `engine/config.py` — all weights, thresholds, paths
- `engine/pipeline.py` — 12-step orchestrator (MVP)
- `engine/database.py` — SQLite schema + helpers
- `engine/transcription.py` — whisper (openai-whisper, soundfile, no ffmpeg subprocess)
- `engine/ingest.py` — video validation via ffprobe
- `engine/analyzers/` — candidate_detector, visual_analyzer, audio_analyzer, virality_scorer, platform_fit
- `engine/renderers/` — clip_generator, reframer (9:16), caption_burner
- `engine/qa/` — video_qa, prepublish_gate (FAIL CLOSED)
- `engine/skills_integration.py` — skill advisor runner

## Skills (global at C:\Users\edupo\.claude\skills\)

All 8 installed as functional placeholders (repos didn't exist on GitHub):
- virality-analyzer, hook-anatomy, trend-radar, platform-fluency
- content-autopsy, repurpose-engine, video-review, video-analyzer

## Dependencies

- ffmpeg: winget Gyan.FFmpeg at `C:\Users\edupo\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_...`
- Python: openai-whisper, cv2, librosa, soundfile, numpy, rich
- VC++ 2022 Redistributable: installed via winget (abbodi1406.vcredist) for torch

**Why:** Transcription uses `soundfile` to load WAV (bypasses whisper's internal ffmpeg subprocess call, which fails when ffmpeg isn't on system PATH).

## Output

`output/clips/` — raw cuts  
`output/clips/*_9x16.mp4` — reframed  
`output/clips/*_9x16_captioned.mp4` — final with captions  

## Security Constraints

- FAIL CLOSED: never publish on rights_not_verified, technical_qa=FAIL, visual_qa=FAIL
- Default mode: REVIEW (not AUTO)
- rights_verified must be explicitly set to True in DB before gate allows PUBLISH

## Pending Etapas

- Etapa 3: REST API, advanced pre-publish gate
- Etapa 4: Job queue, Redis workers
- Etapa 5: Platform adapters (TikTok/Instagram/YouTube official APIs + OAuth)
- Etapa 6: Analytics collector
- Etapa 7: Learning loop + content autopsy feedback
- Etapa 8: Scale
