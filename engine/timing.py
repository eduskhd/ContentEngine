"""Pipeline timing instrumentation — measures each stage and produces a report."""
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StageResult:
    name: str
    start: float
    end: float = 0.0
    status: str = "running"
    error: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if self.end:
            return self.end - self.start
        return time.time() - self.start


class PipelineTimer:
    """Tracks wall-clock time for each pipeline stage.

    Usage:
        t = PipelineTimer(job_id)
        t.start("transcription", model="base")
        words = transcribe(...)
        t.end(words=len(words))
        print(t.report())
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.stages: list[StageResult] = []
        self._active: Optional[StageResult] = None
        self._pipeline_start = time.time()

    def start(self, name: str, **meta) -> "PipelineTimer":
        if self._active:
            # Auto-end any open stage before starting a new one
            self._active.end = time.time()
            self._active.status = "ok"
            self.stages.append(self._active)
        self._active = StageResult(name=name, start=time.time(), meta=dict(meta))
        return self

    def end(self, **meta) -> float:
        if not self._active:
            return 0.0
        self._active.end = time.time()
        self._active.status = "ok"
        self._active.meta.update(meta)
        self.stages.append(self._active)
        duration = self._active.duration
        self._active = None
        return duration

    def fail(self, error: str = "") -> None:
        if self._active:
            self._active.end = time.time()
            self._active.status = "error"
            self._active.error = error
            self.stages.append(self._active)
            self._active = None

    @property
    def total(self) -> float:
        return time.time() - self._pipeline_start

    def report(self) -> str:
        lines = [
            "",
            "=" * 54,
            f"VIDEO PROCESSING REPORT   job={self.job_id[:8]}",
            "=" * 54,
        ]
        for s in self.stages:
            flag = ""
            if s.status == "error":
                flag = " [ERROR]"
            elif s.status == "skip":
                flag = " [CACHED]"
            meta_parts = []
            for k, v in s.meta.items():
                if isinstance(v, float):
                    meta_parts.append(f"{k}={v:.1f}")
                elif v is not None:
                    meta_parts.append(f"{k}={v}")
            meta_str = f"  ({', '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"  {s.name:<32} {s.duration:>7.1f}s{flag}{meta_str}")
        lines.append(f"  {'─' * 52}")
        lines.append(f"  {'TOTAL':<32} {self.total:>7.1f}s")
        lines.append("=" * 54)
        lines.append("")
        return "\n".join(lines)

    def stage_duration(self, name: str) -> float:
        """Return duration of a completed stage by name, 0 if not found."""
        for s in self.stages:
            if s.name == name:
                return s.duration
        return 0.0

    def to_rows(self) -> list[dict]:
        """Return list of dicts suitable for DB insertion."""
        import json
        rows = []
        for s in self.stages:
            rows.append({
                "stage": s.name,
                "start_ts": s.start,
                "end_ts": s.end or s.start,
                "duration_s": s.duration,
                "status": s.status,
                "meta": json.dumps(s.meta) if s.meta else "{}",
            })
        return rows
