"""Content Autopsy — correlates predicted scores with real engagement to tune weights."""
import sqlite3, json
from datetime import datetime

from engine.config import CONFIG


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx * dy > 0 else 0.0


class ContentAutopsy:
    MIN_SAMPLE = 5

    def __init__(self, db_path: str = None):
        self.db_path = db_path or CONFIG.db_path
        self._init_tables()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_tables(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS weight_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    updated_at TEXT,
                    hook_weight REAL,
                    viral_weight REAL,
                    semantic_weight REAL,
                    visual_weight REAL,
                    audio_weight REAL,
                    platform_fit_weight REAL,
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS autopsy_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generated_at TEXT,
                    sample_size INTEGER,
                    correlation_hook REAL,
                    correlation_viral REAL,
                    correlation_visual REAL,
                    correlation_audio REAL,
                    best_hook_type TEXT,
                    optimal_duration_min REAL,
                    optimal_duration_max REAL,
                    recommendations TEXT
                );
            """)

    # ── PUBLIC API ─────────────────────────────────────────────────────────────

    def run_autopsy(self) -> dict:
        """
        Compare predicted scores vs real engagement.
        Returns a report dict. Requires at least MIN_SAMPLE posts with metrics.
        """
        rows = self._load_performance_data()
        if len(rows) < self.MIN_SAMPLE:
            return {"status": "insufficient_data", "sample_size": len(rows), "needed": self.MIN_SAMPLE}

        engagements = [r["engagement_rate"] for r in rows]

        correlations = {
            "hook":     _pearson([r["hook_score"] for r in rows], engagements),
            "viral":    _pearson([r["virality_score"] for r in rows], engagements),
            "visual":   _pearson([r["visual_score"] for r in rows], engagements),
            "audio":    _pearson([r["audio_score"] for r in rows], engagements),
        }

        best_hook = self._best_hook_type(rows)
        opt_min, opt_max = self._optimal_duration(rows)
        recs = self._generate_recommendations(correlations, best_hook, opt_min, opt_max)

        report = {
            "status": "completed",
            "sample_size": len(rows),
            "correlations": correlations,
            "best_hook_type": best_hook,
            "optimal_duration": {"min": opt_min, "max": opt_max},
            "recommendations": recs,
            "generated_at": datetime.utcnow().isoformat(),
        }

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO autopsy_reports
                (generated_at, sample_size, correlation_hook, correlation_viral,
                 correlation_visual, correlation_audio, best_hook_type,
                 optimal_duration_min, optimal_duration_max, recommendations)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, [
                report["generated_at"], len(rows),
                correlations["hook"], correlations["viral"],
                correlations["visual"], correlations["audio"],
                best_hook, opt_min, opt_max,
                json.dumps(recs),
            ])

        return report

    def suggest_weight_adjustments(self) -> dict:
        """
        Based on historical correlations, suggest scoring weight adjustments.
        Does NOT apply automatically — returns suggestions for human review.
        """
        with self._conn() as conn:
            report = conn.execute(
                "SELECT * FROM autopsy_reports ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()

        if not report:
            return {"status": "no_autopsy_data", "hint": "Run POST /learning/autopsy first"}

        corrs = {
            "hook":    max(0.0, report["correlation_hook"]),
            "viral":   max(0.0, report["correlation_viral"]),
            "visual":  max(0.0, report["correlation_visual"]),
            "audio":   max(0.0, report["correlation_audio"]),
        }
        total = sum(corrs.values())
        if total == 0:
            return {"status": "insufficient_correlation"}

        cfg = CONFIG.virality_ensemble
        return {
            "status": "ready",
            "current_weights": {
                "virality_predictor": cfg.virality_predictor,
                "hook": cfg.hook,
                "visual": cfg.visual,
                "audio": cfg.audio,
            },
            "suggested_weights": {k: round(v / total, 3) for k, v in corrs.items()},
            "note": "Review and apply manually by editing engine/config.py ScoringWeights",
            "based_on_report": report["generated_at"],
        }

    # ── INTERNAL ───────────────────────────────────────────────────────────────

    def _load_performance_data(self) -> list:
        with self._conn() as conn:
            return conn.execute("""
                SELECT
                    ca.hook_score, ca.virality_score, ca.visual_score, ca.audio_score,
                    (ca.end_s - ca.start_s) AS duration,
                    pm.engagement_rate, pm.views, pm.platform
                FROM candidates ca
                JOIN clips cl ON cl.candidate_id = ca.id
                JOIN publish_log pl ON pl.clip_id = cl.id
                JOIN post_metrics pm ON pm.clip_id = cl.id AND pm.platform = pl.platform
                WHERE pm.views > 0 AND pm.hours_since_publish >= 24
                ORDER BY pm.collected_at DESC
            """).fetchall()

    def _best_hook_type(self, rows) -> str:
        hook_eng: dict[str, list[float]] = {}
        for r in rows:
            h = dict(r).get("hook_type", "unknown") or "unknown"
            hook_eng.setdefault(h, []).append(r["engagement_rate"])
        if not hook_eng:
            return "unknown"
        return max(hook_eng, key=lambda k: sum(hook_eng[k]) / len(hook_eng[k]))

    def _optimal_duration(self, rows) -> tuple[float, float]:
        sorted_rows = sorted(rows, key=lambda r: r["engagement_rate"], reverse=True)
        top = sorted_rows[:max(1, len(sorted_rows) // 4)]
        durations = [r["duration"] for r in top]
        return min(durations), max(durations)

    def _generate_recommendations(self, corrs: dict, best_hook: str,
                                   opt_min: float, opt_max: float) -> list[str]:
        recs = []
        if corrs["hook"] < 0.3:
            recs.append("Hook score has low correlation with engagement — review hook_analysis scoring criteria")
        if corrs["viral"] > 0.5:
            recs.append("Viral score is strongly predictive — consider increasing its ensemble weight")
        if best_hook not in ("unknown",):
            recs.append(f"'{best_hook}' hooks perform best — prioritize in candidate selection")
        if opt_max - opt_min < 15:
            recs.append(
                f"Optimal clip duration: {opt_min:.0f}s–{opt_max:.0f}s "
                f"— tune min/max_clip_duration in config.py"
            )
        if not recs:
            recs.append("Insufficient variance in data to generate specific recommendations yet")
        return recs
