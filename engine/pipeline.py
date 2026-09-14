"""Pipeline orchestrator: 12-step content processing pipeline.

Performance optimizations (2026-09-10):
- Every stage is timed with PipelineTimer; report printed + persisted at end.
- Proxy video generated after ingest for fast visual analysis.
- Audio and visual analysis run in parallel (ThreadPoolExecutor).
- One-pass rendering: trim + crop + caption burn in a single FFmpeg call per clip.
- Hardware encoding via QSV/NVENC when available.
- Transcript cache: words_json in DB avoids re-transcription on retries.
- Whisper model singleton: loaded once, reused across jobs.
"""
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, wait
from rich.console import Console

from engine.config import EngineConfig, CONFIG
from engine import database as db
from engine.timing import PipelineTimer
from engine.ingest import ingest
from engine.proxy import generate_proxy
from engine.transcription import transcribe
from engine.analyzers.candidate_detector import detect_candidates
from engine.analyzers.visual_analyzer import analyze_visual
from engine.analyzers.audio_analyzer import analyze_audio
from engine.analyzers.virality_scorer import score_virality
from engine.analyzers.platform_fit import analyze_platform_fit
from engine.renderers.render_clip import render_clips_onepass
from engine.qa.video_qa import run_qa
from engine.qa.prepublish_gate import run_prepublish_gate
from engine.skills_integration import run_all_skills
from engine.downloader import is_url, download_url
from engine.analyzers.series_detector import detect_series

console = Console()


def process_video(
    source: str,
    number_of_clips: int = 5,
    target_platforms: list[str] = None,
    creator: str = "unknown",
    content_type: str = "educational",
    config: EngineConfig = None,
    job_id: str = None,
) -> dict:
    cfg = config or CONFIG
    auto_mode = (number_of_clips == 0)
    cfg.target_clips = 20 if auto_mode else number_of_clips
    platforms = target_platforms or ["tiktok", "instagram"]

    # ── PRE-STEP: URL DOWNLOAD ──────────────────────────────────────────────
    download_meta = {}
    if is_url(source):
        console.print(f"[bold cyan]ContentEngine[/] Downloading URL...")
        download_meta = download_url(source)
        source = download_meta["path"]
        if creator == "unknown" and download_meta.get("creator"):
            creator = download_meta["creator"]
        console.print(f"  [green]OK[/] Downloaded: {download_meta['title'][:60]}")
        console.print(f"  Creator: {download_meta['creator']} | Platform: {download_meta['platform']}")

    creator_slug = download_meta.get("creator_slug", _slugify(creator))
    video_slug   = download_meta.get("video_slug", "local")

    if not download_meta:
        from pathlib import Path as _Path
        _fname = _Path(source).stem
        _parts = _fname.split("_", 1)
        _original_name = _parts[1] if len(_parts) == 2 and len(_parts[0]) == 36 else _fname
        download_meta = {
            "title": _original_name,
            "platform": "local",
            "url": source,
            "creator_slug": creator_slug,
            "video_slug": _slugify(_original_name)[:24] or "local",
        }
        video_slug = download_meta["video_slug"]

    job_id = db.create_job(source, cfg.mode, number_of_clips, platforms, creator, content_type,
                           preset_id=job_id)
    console.print(f"\n[bold cyan]ContentEngine[/] job [yellow]{job_id[:8]}[/] | mode=[green]{cfg.mode}[/]")

    timer = PipelineTimer(job_id)

    try:
        # ── STEP 1: INGEST ──────────────────────────────────────────────────
        console.print("[1/12] Ingesting source...")
        db.update_job(job_id, status="INGESTING")
        timer.start("ingest")
        video_id = ingest(job_id, source)
        if download_meta:
            db.update_video(video_id,
                creator_slug=creator_slug,
                video_slug=video_slug,
                source_url=download_meta.get("url", ""),
                source_platform=download_meta.get("platform", ""),
                source_title=download_meta.get("title", ""),
            )
        with db.db() as _c:
            _job_row = _c.execute("SELECT creator_id FROM jobs WHERE id=?", (job_id,)).fetchone()
            _job_creator_id = _job_row["creator_id"] if _job_row else None
        if _job_creator_id:
            db.assign_video_creator(video_id, _job_creator_id)

        with db.db() as conn:
            video_row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        duration_s = video_row["duration_s"]
        src_w = video_row["width"] or 1920
        src_h = video_row["height"] or 1080
        timer.end(duration_s=duration_s, resolution=f"{src_w}x{src_h}")
        console.print(f"  [green]OK[/] Video ingested: {video_id[:8]}")

        # ── STEP 1.5: ANALYSIS PROXY ────────────────────────────────────────
        # Generate a 360p 2fps proxy for fast visual analysis.
        timer.start("proxy_generation")
        proxy_path = generate_proxy(video_id, source)
        timer.end(proxy=proxy_path is not None)
        if proxy_path:
            console.print(f"  [dim]Proxy ready for visual analysis[/]")

        # ── STEP 2: TRANSCRIPTION ───────────────────────────────────────────
        console.print("[2/12] Transcribing audio...")
        db.update_job(job_id, status="TRANSCRIBING")
        timer.start("transcription")
        words = transcribe(job_id, video_id, source)
        # Re-read audio_path from DB (transcription may have set it)
        with db.db() as conn:
            video_row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        audio_path = video_row["audio_path"]
        # Detect cache hit by checking active stage duration before closing it
        _from_cache = (timer._active.duration < 1.0) if timer._active else False
        timer.end(words=len(words), cached=_from_cache)
        console.print(f"  [green]OK[/] {len(words)} word tokens extracted"
                      + (" [dim](cached)[/]" if _from_cache else ""))

        # ── STEP 3: CANDIDATE DETECTION ─────────────────────────────────────
        console.print("[3/12] Detecting candidate windows...")
        db.update_job(job_id, status="ANALYZING")
        timer.start("candidate_detection")
        candidate_ids = detect_candidates(job_id, video_id, words, duration_s)
        timer.end(candidates=len(candidate_ids))
        console.print(f"  [green]OK[/] {len(candidate_ids)} candidates detected")

        if not candidate_ids:
            raise RuntimeError("No viable candidates found in video")

        with db.db() as conn:
            candidate_rows = [
                dict(conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone())
                for cid in candidate_ids
            ]

        # ── STEPS 4+5: VISUAL + AUDIO ANALYSIS (PARALLEL) ──────────────────
        console.print("[4+5/12] Analyzing visual + audio in parallel...")
        timer.start("visual_and_audio_analysis")

        def _visual():
            return analyze_visual(job_id, source, candidate_rows, proxy_path=proxy_path)

        def _audio():
            return analyze_audio(job_id, audio_path, candidate_rows)

        with ThreadPoolExecutor(max_workers=2) as pool:
            vis_future = pool.submit(_visual)
            aud_future = pool.submit(_audio)
            visual_scores = vis_future.result()
            audio_scores = aud_future.result()

        timer.end(candidates=len(candidate_rows))

        # Refresh candidate rows after parallel writes
        with db.db() as conn:
            candidate_rows = [
                dict(conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone())
                for cid in candidate_ids
            ]

        # ── STEP 6: PLATFORM FIT ─────────────────────────────────────────────
        console.print("[6/12] Scoring platform fit...")
        timer.start("platform_fit")
        analyze_platform_fit(job_id, candidate_rows, platforms)
        timer.end()

        with db.db() as conn:
            candidate_rows = [
                dict(conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone())
                for cid in candidate_ids
            ]

        # ── STEP 7: VIRALITY SCORING ──────────────────────────────────────────
        console.print("[7/12] Computing virality ensemble...")
        timer.start("virality_scoring")
        scored = score_virality(job_id, candidate_rows, words, video_duration=duration_s)
        try:
            from engine.analyzers.llm_analyzer import pop_llm_usage
            _llm = pop_llm_usage(job_id)
            timer.end(top_score=round(scored[0]["virality_score"], 1) if scored else 0,
                      llm_tokens_used=_llm["llm_tokens_used"],
                      llm_cost_usd=_llm["llm_cost_usd"])
        except Exception:
            timer.end(top_score=round(scored[0]["virality_score"], 1) if scored else 0)
        if scored:
            console.print(f"  Top score: {scored[0]['virality_score']:.1f} | "
                          f"window {scored[0]['start_s']:.0f}s-{scored[0]['end_s']:.0f}s")

        # ── STEP 7.5: SERIES DETECTION ────────────────────────────────────────
        series_ids = []
        if cfg.generate_series and words:
            console.print("[7.5] Detecting narrative series...")
            timer.start("series_detection")
            try:
                series_ids = detect_series(job_id, video_id, candidate_rows, words)
                timer.end(series=len(series_ids))
                if series_ids:
                    console.print(f"  {len(series_ids)} series detected")
            except Exception as _se:
                timer.fail(str(_se))
                console.print(f"  Series detection skipped: {_se}")

        # ── STEP 8: SKILLS ADVISORS ───────────────────────────────────────────
        console.print("[8/12] Running skill advisors...")
        timer.start("skills")
        top_finalists = scored[:cfg.target_clips * cfg.finalist_multiplier]
        finalist_rows = [r for r in candidate_rows
                         if r["id"] in {c["id"] for c in top_finalists}]
        run_all_skills(job_id, finalist_rows, platforms, words)
        timer.end()

        with db.db() as conn:
            finalist_rows = [
                dict(conn.execute("SELECT * FROM candidates WHERE id=?", (r["id"],)).fetchone())
                for r in finalist_rows
            ]
        finalist_rows.sort(key=lambda x: x["virality_score"], reverse=True)

        if auto_mode:
            AUTO_QUALITY_THRESHOLD = 40.0
            final_selection = [r for r in finalist_rows
                               if r.get("virality_score", 0) >= AUTO_QUALITY_THRESHOLD]
            if not final_selection:
                final_selection = finalist_rows[:3]
            console.print(f"  AUTO mode: {len(final_selection)} clips above threshold {AUTO_QUALITY_THRESHOLD}")
        else:
            final_selection = finalist_rows[:number_of_clips]

        # ── STEPS 9-11: ONE-PASS RENDER (trim + reframe + captions) ──────────
        console.print(f"[9-11/12] Rendering {len(final_selection)} clips (trim+reframe+captions, 1 pass)...")
        db.update_job(job_id, status="RENDERING")
        timer.start("render_all_clips")
        output_subdir = f"{creator_slug}/{video_slug}"
        clip_ids = render_clips_onepass(
            job_id=job_id,
            source=source,
            finalists=final_selection,
            words=words,
            src_w=src_w,
            src_h=src_h,
            output_subdir=output_subdir,
        )
        timer.end(clips=len(clip_ids))
        console.print(f"  [green]OK[/] {len(clip_ids)} clips rendered")

        # ── STEP 12: QA + PRE-PUBLISH GATE ───────────────────────────────────
        console.print("[12/12] Running QA + pre-publish gate...")
        db.update_job(job_id, status="QA")
        timer.start("qa_and_gate")
        qa_results = run_qa(job_id, clip_ids)
        gate_results = run_prepublish_gate(job_id, clip_ids, platforms)
        timer.end()

        publish_count = sum(1 for d in gate_results.values() if d == "PUBLISH")
        review_count  = sum(1 for d in gate_results.values() if d == "REVIEW")
        reject_count  = sum(1 for d in gate_results.values() if d == "REJECT")

        # ── TIMING REPORT ─────────────────────────────────────────────────────
        try:
            console.print(timer.report())
        except Exception:
            pass

        # Persist timing to DB
        try:
            db.save_pipeline_timings(job_id, timer.to_rows())
        except Exception:
            pass

        try:
            _print_summary(job_id, clip_ids, qa_results, gate_results, cfg.mode)
        except Exception:
            pass

        db.update_job(job_id, status="COMPLETED")

        return {
            "job_id": job_id,
            "video_id": video_id,
            "creator": creator,
            "creator_slug": creator_slug,
            "video_slug": video_slug,
            "source_title": download_meta.get("title", ""),
            "source_platform": download_meta.get("platform", "local"),
            "clips": _build_clip_report(job_id, clip_ids, qa_results, gate_results),
            "stats": {
                "candidates": len(candidate_ids),
                "clips_generated": len(clip_ids),
                "publish": publish_count,
                "review": review_count,
                "reject": reject_count,
                "series_detected": len(series_ids),
                "total_time_s": round(timer.total, 1),
            },
            "series_ids": series_ids,
            "timing": {s.name: round(s.duration, 1) for s in timer.stages},
        }

    except Exception as e:
        db.update_job(job_id, status="FAILED", error=str(e))
        console.print(f"[red]FAIL Pipeline failed:[/] {e}")
        traceback.print_exc()
        raise


def _slugify(text: str) -> str:
    import re
    text = str(text).lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text).strip("_")
    return text[:40] or "unknown"


def _build_clip_report(job_id, clip_ids, qa_results, gate_results):
    with db.db() as conn:
        clips = []
        for cid in clip_ids:
            row = conn.execute("SELECT * FROM clips WHERE id=?", (cid,)).fetchone()
            cand = conn.execute(
                "SELECT * FROM candidates WHERE id=?", (row["candidate_id"],)
            ).fetchone()
            clips.append({
                "clip_id": cid[:8],
                "path": row["captioned_path"] or row["output_path"],
                "duration_s": row["duration_s"],
                "resolution": f"{row['width']}x{row['height']}",
                "technical_qa": row["technical_qa"],
                "visual_qa": row["visual_qa"],
                "prepublish": gate_results.get(cid, "PENDING"),
                "virality_score": cand["virality_score"] if cand else 0,
            })
    return clips


def _print_summary(job_id, clip_ids, qa_results, gate_results, mode):
    console.print(f"\n[bold]── ContentEngine Results ──[/]")
    console.print(f"Job: [yellow]{job_id[:8]}[/]  Mode: [green]{mode}[/]\n")
    with db.db() as conn:
        for i, cid in enumerate(clip_ids, 1):
            row = conn.execute("SELECT * FROM clips WHERE id=?", (cid,)).fetchone()
            cand = conn.execute(
                "SELECT * FROM candidates WHERE id=?", (row["candidate_id"],)
            ).fetchone()
            decision = gate_results.get(cid, "PENDING")
            color = "green" if decision == "PUBLISH" else "yellow" if decision == "REVIEW" else "red"
            console.print(
                f"  [{i}] {cand['start_s']:.0f}s-{cand['end_s']:.0f}s | "
                f"virality={cand['virality_score']:.1f} | [{color}]{decision}[/]"
            )
    console.print()
