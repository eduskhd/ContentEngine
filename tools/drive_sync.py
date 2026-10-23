"""Google Drive export tool for ContentEngine experiments.

Uses the Google Drive REST API — no Drive for Desktop required.
Auth: OAuth 2.0 Desktop flow. One-time browser login, then runs headlessly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ONE-TIME SETUP (do once)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

  2. Google Cloud Console (browser):
     a. https://console.cloud.google.com/
     b. New project -> any name (e.g. "ContentEngine")
     c. APIs & Services -> Library -> search "Drive" -> Enable Google Drive API
     d. APIs & Services -> Credentials -> + Create Credentials -> OAuth 2.0 Client ID
     e. Application type: Desktop app -> name it anything -> CREATE
     f. Download JSON -> save as:  tools/credentials.json   (in this repo)

  3. python tools/drive_sync.py --setup
     (opens browser tab, you click Allow, done -- saves token locally)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

USAGE:
    python tools/drive_sync.py --experiment experiments/smart_reframing_v1_2
    python tools/drive_sync.py --experiment experiments/smart_reframing_v1_2 --dry-run
    python tools/drive_sync.py --verify-last
    python tools/drive_sync.py --setup
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ── Project root ──────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent

# ── Authorised Drive destination ──────────────────────────────────────────────

DRIVE_ROOT_FOLDER_ID = "1J6P3WqZnrBPX2TLcvMwc-wi50RxIp162"
EXPECTED_SUBFOLDERS  = ["latest", "contact_sheets", "history"]

# Local auth files (never exported to Drive)
CREDENTIALS_FILE = REPO_ROOT / "tools" / "credentials.json"
TOKEN_FILE       = REPO_ROOT / "tools" / ".drive_token.json"
EXPORT_LOG       = REPO_ROOT / "tools" / "drive_export_log.jsonl"

# ── OAuth scopes ──────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/drive"]

# ── Security: files NEVER to export ───────────────────────────────────────────

BLOCKED_EXTENSIONS = {
    ".sqlite", ".db", ".env", ".key", ".pem", ".p12", ".pfx",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".py", ".pyc", ".pyo",
    ".sh", ".bat", ".ps1",
    ".log",
    ".zip", ".tar", ".gz", ".7z",
}

BLOCKED_NAME_PATTERNS = [
    r"token",
    r"credentials",
    r"secret",
    r"cookie",
    r"password",
    r"\.env",
    r"engine\.sqlite",
]

REPORT_FILENAMES = {
    "FINAL_REPORT.md",
    "REGRESSION_REPORT.md",
    "VISUAL_COMPARISON.md",
    "PERFORMANCE.md",
    "TEST_RESULTS.md",
    "SCENE_ANALYSIS.md",
    "ARCHITECTURE.md",
    "BASELINE.md",
    "QA_REPORT.md",
    "manifest.json",
    # gaming stacked compositor fix
    "ROOT_CAUSE.md",
    "FILTERGRAPH_AUDIT.md",
    "LAYOUT_RATIO_TESTS.md",
    "PREVIEW_RENDER_PARITY.md",
    # crop precision repair
    "ROOT_CAUSE_ANALYSIS.md",
    "GEOMETRY_CONTRACT.md",
    "CROP_ACCURACY_TESTS.md",
    "LAYOUT_COMPARISON.md",
    "OPEN_SOURCE_RESEARCH.md",
    # platform stability audit
    "DATABASE_AUDIT.md",
    "FRONTEND_AUDIT.md",
    "BACKEND_AUDIT.md",
    "DATA_MODEL.md",
    "WORKER_ISOLATION.md",
    "STORAGE_ARCHITECTURE.md",
    "BASELINE_PERFORMANCE.md",
    "MIGRATION_ROADMAP.md",
    "STORAGE_INVENTORY.md",
    "LIBRARY_REPAIR.md",
    "BENCHMARK_RESULTS.md",
    "PROGRESS.md",
    "E2E_TEST_RESULTS.md",
    # library & media architecture audit
    "CURRENT_SCHEMA_MAP.md",
    "TARGET_DATA_MODEL.md",
    "SCHEMA_MIGRATION_PLAN.md",
    "PACKAGE_INTEGRITY.md",
    "MEDIA_STORAGE_DESIGN.md",
    "CLEANUP_PROPOSAL.md",
    "FILTERS_AND_SORTING.md",
    "PAGINATION_TESTS.md",
    "LIBRARY_FUNCTIONAL_AUDIT.md",
    "REGRESSION_REPORT.md",
}


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FileRecord:
    name: str
    src_path: str
    drive_file_id: str
    size_bytes: int
    sha256: str
    section: str     # latest | contact_sheets
    status: str = "pending"
    error: str = ""


@dataclass
class ExportRecord:
    experiment_id: str
    exported_at: str
    drive_root_id: str
    dry_run: bool
    files: list[FileRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "pending"


# ── Dependency check ──────────────────────────────────────────────────────────

def require_google_api():
    try:
        from googleapiclient.discovery import build          # noqa: F401
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from google.auth.transport.requests import Request   # noqa: F401
    except ImportError:
        print("Google API packages not installed.\n")
        print("Run:")
        print("  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        sys.exit(1)


# ── Auth ──────────────────────────────────────────────────────────────────────

def build_drive_service():
    """Return an authenticated Drive v3 service. Refreshes token if needed."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f"credentials.json not found at {CREDENTIALS_FILE}")
                print()
                print("Follow the one-time setup instructions at the top of this file.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        print(f"Token saved: {TOKEN_FILE}")

    return build("drive", "v3", credentials=creds)


# ── Drive folder utilities ────────────────────────────────────────────────────

def drive_find_subfolder(service, parent_id: str, name: str) -> Optional[str]:
    """Return folder ID if a subfolder named `name` exists under `parent_id`."""
    q = (
        f"'{parent_id}' in parents "
        f"and name = '{name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    result = service.files().list(q=q, fields="files(id, name)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def drive_create_subfolder(service, parent_id: str, name: str) -> str:
    """Create a folder under parent_id and return its ID."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    f = service.files().create(body=metadata, fields="id").execute()
    return f["id"]


def drive_get_or_create_subfolder(service, parent_id: str, name: str, dry_run: bool) -> Optional[str]:
    """Find or create a subfolder. Returns None in dry-run mode."""
    existing = drive_find_subfolder(service, parent_id, name)
    if existing:
        return existing
    if dry_run:
        print(f"  [DRY] Would create subfolder: {name}/")
        return None
    fid = drive_create_subfolder(service, parent_id, name)
    print(f"  [OK]  Created subfolder: {name}/ (id={fid[:16]}...)")
    return fid


def drive_verify_root(service) -> None:
    """Abort if the root folder does not exist or is not accessible."""
    try:
        f = service.files().get(
            fileId=DRIVE_ROOT_FOLDER_ID,
            fields="id, name, mimeType, trashed"
        ).execute()
    except Exception as e:
        raise RuntimeError(
            f"Cannot access Drive folder ID {DRIVE_ROOT_FOLDER_ID}: {e}\n"
            "Make sure you authenticated with the account that owns this folder."
        )
    if f.get("trashed"):
        raise RuntimeError(f"Drive folder {DRIVE_ROOT_FOLDER_ID} is in the trash.")
    if f.get("mimeType") != "application/vnd.google-apps.folder":
        raise RuntimeError(f"ID {DRIVE_ROOT_FOLDER_ID} is not a folder.")
    print(f"Drive root verified: '{f['name']}' (id={f['id'][:16]}...)")


def drive_list_files_in(service, folder_id: str) -> list[dict]:
    """Return list of non-folder file dicts in a folder."""
    q = (
        f"'{folder_id}' in parents "
        f"and mimeType != 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    result = service.files().list(q=q, fields="files(id, name, size)").execute()
    return result.get("files", [])


def drive_move_file(service, file_id: str, dst_folder_id: str, current_parent_id: str) -> None:
    """Move a file from current_parent_id to dst_folder_id."""
    service.files().update(
        fileId=file_id,
        addParents=dst_folder_id,
        removeParents=current_parent_id,
        fields="id, parents",
    ).execute()


def drive_upload_file(service, src: Path, parent_id: str, mime_type: str = "text/plain") -> str:
    """Upload a file and return its Drive file ID."""
    from googleapiclient.http import MediaFileUpload
    metadata = {"name": src.name, "parents": [parent_id]}
    media = MediaFileUpload(str(src), mimetype=mime_type, resumable=False)
    f = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return f["id"]


def drive_upload_text(service, name: str, content: str, parent_id: str) -> str:
    """Upload an in-memory string as a plain-text file. Returns Drive file ID."""
    import io
    from googleapiclient.http import MediaIoBaseUpload
    metadata = {"name": name, "parents": [parent_id]}
    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="text/plain")
    f = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return f["id"]


# ── Security scanner ──────────────────────────────────────────────────────────

def is_safe_to_export(path: Path) -> tuple[bool, str]:
    name_lower = path.name.lower()
    if path.suffix.lower() in BLOCKED_EXTENSIONS:
        return False, f"blocked extension: {path.suffix}"
    for pattern in BLOCKED_NAME_PATTERNS:
        if re.search(pattern, name_lower, re.IGNORECASE):
            return False, f"blocked name pattern: {pattern}"
    if path.suffix.lower() in (".json", ".md"):
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[:4096]
            leak_patterns = [
                r"client_secret_",
                r'"type"\s*:\s*"service_account"',
                r"PRIVATE KEY",
                r"AIza[A-Za-z0-9_\-]{35}",
                r"ya29\.",
            ]
            for lp in leak_patterns:
                if re.search(lp, sample):
                    return False, f"potential secret in content: {lp}"
        except Exception:
            pass
    return True, ""


# ── Hash ──────────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Experiment discovery ──────────────────────────────────────────────────────

def validate_experiment_complete(exp_dir: Path) -> None:
    for r in ["FINAL_REPORT.md", "manifest.json"]:
        if not (exp_dir / r).exists():
            raise RuntimeError(f"Experiment incomplete: missing {r} in {exp_dir}")


def discover_reports(exp_dir: Path) -> list[Path]:
    results = []
    for p in exp_dir.iterdir():
        if not p.is_file() or p.name not in REPORT_FILENAMES:
            continue
        safe, reason = is_safe_to_export(p)
        if safe:
            results.append(p)
        else:
            print(f"  [SKIP] {p.name}: {reason}")
    return sorted(results)


def discover_contact_sheets(exp_dir: Path) -> list[Path]:
    cs_dir = exp_dir / "contact_sheets"
    if not cs_dir.exists():
        return []
    results = []
    for pattern in ("*.png", "*.jpg", "*.jpeg"):
        for p in cs_dir.glob(pattern):
            safe, reason = is_safe_to_export(p)
            if safe:
                results.append(p)
            else:
                print(f"  [SKIP] {p.name}: {reason}")
    return sorted(results)


# ── INDEX.md ──────────────────────────────────────────────────────────────────

def generate_index(
    exp_dir: Path,
    reports: list[Path],
    sheets: list[Path],
    record: ExportRecord,
    dry_run: bool,
) -> str:
    manifest_path = exp_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    experiment_id = exp_dir.name
    clips    = manifest.get("clips", {})
    n_clips  = len(clips) if isinstance(clips, dict) else len(clips)
    tests    = manifest.get("tests", {})
    summary  = manifest.get("summary", {})

    lines = [
        "# ContentEngine AI Review -- Index",
        "",
        "**Project:** ContentEngine (AI Short-Form Video Engine)",
        f"**Experiment:** `{experiment_id}`",
        f"**Exported:** {record.exported_at}",
        f"**Dry run:** {'YES -- files not actually uploaded' if dry_run else 'NO -- files are live in Drive'}",
        "",
        "## Experiment summary",
        "",
        f"- Clips processed: {n_clips}",
        "- Variants per clip: 3 (Original, V1.1, V1.2)",
        f"- Tests passed: {tests.get('passed', '?')}/{tests.get('count', '?')}",
        f"- Avg plan time: {summary.get('avg_plan_s', '?')}s",
        f"- Avg render time: {summary.get('avg_render_s', '?')}s",
        "",
        "## Reports (in latest/)",
        "",
    ]
    for f in sorted(reports, key=lambda p: p.name):
        rec = next((r for r in record.files if r.name == f.name and r.section == "latest"), None)
        sha = (rec.sha256[:16] + "...") if rec else "?"
        fid = (rec.drive_file_id[:16] + "...") if rec and rec.drive_file_id else "?"
        lines.append(f"- `{f.name}` -- Drive id: `{fid}` -- sha256: `{sha}`")

    lines += ["", "## Contact sheets (in contact_sheets/)", ""]
    for f in sorted(sheets, key=lambda p: p.name):
        rec = next((r for r in record.files if r.name == f.name and r.section == "contact_sheets"), None)
        sha = (rec.sha256[:16] + "...") if rec else "?"
        fid = (rec.drive_file_id[:16] + "...") if rec and rec.drive_file_id else "?"
        lines.append(f"- `{f.name}` -- Drive id: `{fid}` -- sha256: `{sha}`")

    lines += [
        "",
        "## Key results",
        "",
        "- Smart Reframing V1.2: scene classification (7 types), ConfidenceGate dead zone (+-0.05), adaptive split fraction (0.55-0.72), HUD detection.",
        "- IlloJuan_04b85e28: only SPLIT_LAYOUT clip; V1.2 applied 65% split fraction vs V1.1 60%.",
        "- All 6 clips classified as static_gameplay (proxies are center-cropped 9:16, lower apparent motion).",
        "- V1.2 plan overhead vs V1.1: +0.18s (+5.2%). Render time unchanged.",
        "- Rickyedit: 6 HUD regions detected (highest density).",
        "",
        "## Known limitations",
        "",
        "- Input clips were 9:16 (from V1.1 experiment). In production V1.2 runs on 16:9 source where facecam detection is reliable.",
        "- HUD penalty stored but not yet used in crop selection (planned for V1.3).",
        "",
        "## Files NOT included",
        "",
        "- MP4 videos, SQLite, source code, credentials, tokens, API keys (excluded per security policy)",
        "",
        "*Generated by tools/drive_sync.py -- ContentEngine*",
    ]
    return "\n".join(lines) + "\n"


# ── Archive latest/ ───────────────────────────────────────────────────────────

def archive_previous_latest(
    service,
    latest_folder_id: str,
    history_folder_id: str,
    experiment_id: str,
    dry_run: bool,
) -> None:
    existing = drive_list_files_in(service, latest_folder_id)
    if not existing:
        return

    date_str     = datetime.date.today().isoformat()
    archive_name = f"{experiment_id}_{date_str}"

    if drive_find_subfolder(service, history_folder_id, archive_name):
        archive_name = f"{archive_name}_2"

    if dry_run:
        print(f"  [DRY] Would archive {len(existing)} files -> history/{archive_name}/")
        return

    archive_id = drive_create_subfolder(service, history_folder_id, archive_name)
    for f in existing:
        drive_move_file(service, f["id"], archive_id, latest_folder_id)
    print(f"  [OK]  Archived {len(existing)} files -> history/{archive_name}/")


# ── Upload a single file ──────────────────────────────────────────────────────

def upload_file(service, src: Path, folder_id: str, section: str, dry_run: bool) -> FileRecord:
    sha       = sha256_file(src)
    size      = src.stat().st_size
    mime_type = (
        "image/png"        if src.suffix.lower() == ".png"          else
        "image/jpeg"       if src.suffix.lower() in (".jpg", ".jpeg") else
        "application/json" if src.suffix.lower() == ".json"         else
        "text/plain"
    )
    rec = FileRecord(
        name=src.name, src_path=str(src), drive_file_id="",
        size_bytes=size, sha256=sha, section=section,
    )
    if dry_run:
        print(f"  [DRY] {section}/{src.name} ({size // 1024} KB)")
        rec.status = "dry_run"
        return rec
    try:
        fid = drive_upload_file(service, src, folder_id, mime_type)
        rec.drive_file_id = fid
        rec.status        = "ok"
        print(f"  [OK]  {section}/{src.name} ({size // 1024} KB) id={fid[:16]}...")
    except Exception as e:
        rec.status = "error"
        rec.error  = str(e)
        print(f"  [ERR] {section}/{src.name}: {e}")
    return rec


# ── Log ───────────────────────────────────────────────────────────────────────

def write_log(record: ExportRecord) -> None:
    EXPORT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPORT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), default=str) + "\n")


# ── Main export ───────────────────────────────────────────────────────────────

def export(service, exp_dir: Path, dry_run: bool) -> ExportRecord:
    experiment_id = exp_dir.name
    now = datetime.datetime.now().isoformat(timespec="seconds")

    record = ExportRecord(
        experiment_id=experiment_id,
        exported_at=now,
        drive_root_id=DRIVE_ROOT_FOLDER_ID,
        dry_run=dry_run,
    )

    print(f"\nExporting: {experiment_id}")
    print(f"Drive folder ID: {DRIVE_ROOT_FOLDER_ID}")
    print(f"Dry run: {dry_run}")
    print()

    try:
        validate_experiment_complete(exp_dir)
    except RuntimeError as e:
        record.errors.append(str(e))
        record.status = "error"
        print(f"[ABORT] {e}")
        return record

    if not dry_run:
        try:
            drive_verify_root(service)
        except RuntimeError as e:
            record.errors.append(str(e))
            record.status = "error"
            print(f"[ABORT] {e}")
            return record

    print("--- Verifying subfolder structure ---")
    if dry_run:
        latest_id  = None
        cs_id      = None
        history_id = None
        for sf in EXPECTED_SUBFOLDERS:
            print(f"  [DRY] Would ensure subfolder: {sf}/")
    else:
        latest_id  = drive_get_or_create_subfolder(service, DRIVE_ROOT_FOLDER_ID, "latest", False)
        cs_id      = drive_get_or_create_subfolder(service, DRIVE_ROOT_FOLDER_ID, "contact_sheets", False)
        history_id = drive_get_or_create_subfolder(service, DRIVE_ROOT_FOLDER_ID, "history", False)
    print()

    reports = discover_reports(exp_dir)
    sheets  = discover_contact_sheets(exp_dir)
    print(f"Reports found: {len(reports)}")
    print(f"Contact sheets found: {len(sheets)}")
    print()

    print("--- Archiving previous latest/ ---")
    if not dry_run and latest_id and history_id:
        archive_previous_latest(service, latest_id, history_id, experiment_id, dry_run)
    elif dry_run:
        print("  [DRY] Would archive any existing latest/ files to history/")
    print()

    print("--- Uploading reports to latest/ ---")
    for src in reports:
        rec = upload_file(service, src, latest_id or "", "latest", dry_run)
        record.files.append(rec)
    print()

    print("--- Uploading contact sheets ---")
    for src in sheets:
        rec = upload_file(service, src, cs_id or "", "contact_sheets", dry_run)
        record.files.append(rec)
    print()

    print("--- Uploading INDEX.md ---")
    index_content = generate_index(exp_dir, reports, sheets, record, dry_run)
    if dry_run:
        print(f"  [DRY] INDEX.md ({len(index_content)} bytes)")
        record.files.append(FileRecord(
            name="INDEX.md", src_path="(generated)", drive_file_id="",
            size_bytes=len(index_content.encode()), sha256="(dry-run)",
            section="latest", status="dry_run",
        ))
    else:
        try:
            fid = drive_upload_text(service, "INDEX.md", index_content, latest_id)
            record.files.append(FileRecord(
                name="INDEX.md", src_path="(generated)", drive_file_id=fid,
                size_bytes=len(index_content.encode()),
                sha256=hashlib.sha256(index_content.encode()).hexdigest(),
                section="latest", status="ok",
            ))
            print(f"  [OK]  INDEX.md ({len(index_content)} bytes) id={fid[:16]}...")
        except Exception as e:
            record.errors.append(f"INDEX.md: {e}")
            print(f"  [ERR] INDEX.md: {e}")
    print()

    errors   = [f for f in record.files if f.status == "error"]
    ok_files = [f for f in record.files if f.status == "ok"]
    record.status = "error" if errors else ("dry_run" if dry_run else "ok")

    print("=" * 60)
    if dry_run:
        dr_count = sum(1 for f in record.files if f.status == "dry_run")
        print(f"DRY RUN complete: {dr_count} files would be uploaded")
    else:
        print(f"Export complete: {len(ok_files)} OK, {len(errors)} errors")
        if errors:
            for e in errors:
                print(f"  ERROR {e.name}: {e.error}")
        print()
        print(f"View in Drive: https://drive.google.com/drive/folders/{DRIVE_ROOT_FOLDER_ID}")

    return record


# ── Verify last export ────────────────────────────────────────────────────────

def verify_last_export(service) -> None:
    if not EXPORT_LOG.exists():
        print("No export log found.")
        return
    lines = EXPORT_LOG.read_text(encoding="utf-8").strip().split("\n")
    last  = json.loads(lines[-1])
    print(f"Last export: {last['experiment_id']} at {last['exported_at']}")

    errors = 0
    for f in last["files"]:
        if f["status"] != "ok" or not f["drive_file_id"]:
            continue
        try:
            meta = service.files().get(
                fileId=f["drive_file_id"], fields="id, name, size, trashed"
            ).execute()
            if meta.get("trashed"):
                print(f"  [WARN] {f['name']}: file is in Drive trash")
                errors += 1
            else:
                print(f"  [OK]   {f['name']} still exists in Drive")
        except Exception as e:
            print(f"  [ERR]  {f['name']}: {e}")
            errors += 1

    print()
    print(f"Verification: {'PASS' if errors == 0 else f'FAIL ({errors} issues)'}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ContentEngine -> Google Drive exporter")
    parser.add_argument("--experiment",   help="Path to experiment dir (absolute or relative to repo root)")
    parser.add_argument("--dry-run",      action="store_true", help="Show what would happen, no uploads")
    parser.add_argument("--verify-last",  action="store_true", help="Re-verify last export's Drive files")
    parser.add_argument("--setup",        action="store_true", help="Run OAuth setup (opens browser)")
    args = parser.parse_args()

    require_google_api()

    if args.setup:
        print("Starting OAuth setup -- a browser tab will open.")
        build_drive_service()
        print("Authentication complete.")
        print(f"Token stored at: {TOKEN_FILE}")
        print()
        print("Now run:")
        print("  python tools/drive_sync.py --experiment experiments/smart_reframing_v1_2 --dry-run")
        return

    try:
        service = build_drive_service()
    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        print("Run:  python tools/drive_sync.py --setup")
        sys.exit(1)

    if args.verify_last:
        verify_last_export(service)
        return

    if not args.experiment:
        parser.print_help()
        sys.exit(1)

    exp_dir = Path(args.experiment)
    if not exp_dir.is_absolute():
        exp_dir = REPO_ROOT / args.experiment
    if not exp_dir.exists():
        print(f"[ERROR] Experiment directory not found: {exp_dir}")
        sys.exit(1)

    record = export(service, exp_dir, args.dry_run)

    if not args.dry_run:
        write_log(record)
        print(f"Log: {EXPORT_LOG}")

    sys.exit(0 if record.status in ("ok", "dry_run") else 1)


if __name__ == "__main__":
    main()
