"""ローカル専用の公演メンテナンス画面とJSON APIを提供する。"""
from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
import shutil
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit, parse_qs
import webbrowser

from build_event_cumulative import load_rows
from github_artifact_sync import ArtifactSyncError, sync_latest_artifact
from location_normalization import extract_prefecture
from manual_event_overrides import (
    ManualOverrideError,
    apply_manual_event_overrides,
    delete_manual_event_override,
    load_manual_event_overrides,
    now_iso,
    override_revision,
    split_source_tweet_urls,
    upsert_manual_event_override,
    write_manual_event_overrides,
)
from rebuild_maintained_outputs import rebuild_maintained_outputs


ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "maintenance_web"
MAX_BODY_SIZE = 256 * 1024


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class MaintenanceService:
    def __init__(self, root_dir: Path = ROOT_DIR):
        self.root_dir = root_dir.resolve()
        self.output_dir = self.root_dir / "data/output"
        self.base_csv = self.output_dir / "event_cumulative_base.csv"
        self.effective_csv = self.output_dir / "event_cumulative.csv"
        self.schedule_csv = self.output_dir / "schedule_list.csv"
        self.schedule_json = self.output_dir / "schedule_list.json"
        self.overrides_json = self.root_dir / "config/manual_event_overrides.json"
        self.organization_master = self.output_dir / "organization_master.csv"
        self.venue_master = self.output_dir / "venue_master.csv"
        self.sync_state = self.output_dir / "_tmp/maintenance_sync_state.json"
        self._lock = threading.RLock()

    def _load_rows_if_exists(self, path: Path) -> list[dict[str, str]]:
        return load_rows(path) if path.exists() else []

    def _load_schedule(self) -> dict[str, Any]:
        if not self.schedule_json.exists():
            return {"generated_at": "", "count": 0, "items": []}
        try:
            payload = json.loads(self.schedule_json.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ApiError(500, "ローカルのscheduleデータを読み込めません") from exc
        return payload if isinstance(payload, dict) else {"generated_at": "", "count": 0, "items": []}

    def _load_sync_state(self) -> dict[str, Any]:
        if not self.sync_state.exists():
            return {}
        try:
            payload = json.loads(self.sync_state.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _git(self, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=self.root_dir,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            shell=False,
        )
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Gitの処理に失敗しました").strip().splitlines()
            raise ApiError(409, detail[-1] if detail else "Gitの処理に失敗しました")
        return completed

    def git_status(self) -> dict[str, Any]:
        try:
            branch = self._git(["branch", "--show-current"]).stdout.strip()
            status_lines = self._git(["status", "--short"]).stdout.splitlines()
            override_status = self._git(
                ["status", "--short", "--", "config/manual_event_overrides.json"]
            ).stdout.strip()
            return {
                "available": True,
                "branch": branch,
                "dirty_count": len(status_lines),
                "override_changed": bool(override_status),
            }
        except (FileNotFoundError, ApiError):
            return {"available": False, "branch": "", "dirty_count": 0, "override_changed": False}

    def gh_status(self) -> dict[str, bool]:
        if shutil.which("gh") is None:
            return {"available": False, "authenticated": False}
        completed = subprocess.run(
            ["gh", "auth", "status"],
            cwd=self.root_dir,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            shell=False,
        )
        return {"available": True, "authenticated": completed.returncode == 0}

    def _override_application_stats(self) -> dict[str, Any]:
        payload = load_manual_event_overrides(self.overrides_json)
        base_rows = self._load_rows_if_exists(self.base_csv)
        _, stats = apply_manual_event_overrides(base_rows, payload["overrides"])
        return {**stats, "override_count": len(payload["overrides"])}

    def status(self) -> dict[str, Any]:
        with self._lock:
            base_rows = self._load_rows_if_exists(self.base_csv)
            effective_rows = self._load_rows_if_exists(self.effective_csv)
            stats = self._override_application_stats()
            schedule = self._load_schedule()
            return {
                "gh": self.gh_status(),
                "git": self.git_status(),
                "sync": self._load_sync_state(),
                "counts": {
                    "base": len(base_rows),
                    "effective": len(effective_rows),
                    "schedule": int(schedule.get("count") or 0),
                    "overrides": stats["override_count"],
                    "orphan": len(stats["orphan"]),
                    "ambiguous": len(stats["ambiguous"]),
                },
                "orphan": stats["orphan"],
                "ambiguous": stats["ambiguous"],
                "revision": override_revision(load_manual_event_overrides(self.overrides_json)),
            }

    def rebuild(self) -> dict[str, Any]:
        return rebuild_maintained_outputs(
            base_csv=self.base_csv,
            overrides_json=self.overrides_json,
            effective_csv=self.effective_csv,
            organization_master_csv=self.organization_master,
            venue_master_csv=self.venue_master,
            schedule_csv=self.schedule_csv,
            schedule_json=self.schedule_json,
        )

    def sync(self) -> dict[str, Any]:
        with self._lock:
            result = sync_latest_artifact(root_dir=self.root_dir)
            result["rebuild"] = self.rebuild()
            return result

    def _event_data(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], str]:
        base_rows = self._load_rows_if_exists(self.base_csv)
        effective_rows = self._load_rows_if_exists(self.effective_csv)
        base_by_id = {str(row.get("event_id") or ""): row for row in base_rows}
        effective_by_id = {str(row.get("event_id") or ""): row for row in effective_rows}
        payload = load_manual_event_overrides(self.overrides_json)
        overrides_by_id = {item["target_event_id"]: item for item in payload["overrides"]}
        return base_rows, base_by_id, effective_by_id, overrides_by_id, override_revision(payload)

    def events(self, query: dict[str, list[str]]) -> dict[str, Any]:
        with self._lock:
            base_rows, base_by_id, effective_by_id, overrides_by_id, revision = self._event_data()
            schedule_by_id = {
                str(item.get("event_id") or ""): item
                for item in self._load_schedule().get("items", [])
                if isinstance(item, dict)
            }
            keyword = (query.get("q", [""])[0] or "").strip().lower()
            publication = (query.get("publication", [""])[0] or "").strip().lower()
            prefecture = (query.get("prefecture", [""])[0] or "").strip()
            items: list[dict[str, Any]] = []
            for base in base_rows:
                event_id = str(base.get("event_id") or "")
                effective = effective_by_id.get(event_id, base)
                override = overrides_by_id.get(event_id)
                status = str(effective.get("manual_publish_status") or "default").lower()
                location = str(effective.get("normalized_location") or effective.get("location") or "")
                item_prefecture = extract_prefecture(location)
                haystack = " ".join(
                    str(effective.get(field) or "")
                    for field in ("event_name", "organization", "venue_name", "normalized_location")
                ).lower()
                if keyword and keyword not in haystack:
                    continue
                if publication and status != publication:
                    continue
                if prefecture and item_prefecture != prefecture:
                    continue
                items.append(
                    {
                        "event_id": event_id,
                        "base": base,
                        "effective": effective,
                        "override": override,
                        "has_override": override is not None,
                        "prefecture": item_prefecture,
                        "schedule": schedule_by_id.get(event_id),
                    }
                )
            return {"items": items, "count": len(items), "revision": revision}

    def event(self, event_id: str) -> dict[str, Any]:
        with self._lock:
            _, base_by_id, effective_by_id, overrides_by_id, revision = self._event_data()
            base = base_by_id.get(event_id)
            if base is None:
                raise ApiError(404, "指定した公演が見つかりません")
            schedule = next(
                (
                    item
                    for item in self._load_schedule().get("items", [])
                    if isinstance(item, dict) and str(item.get("event_id") or "") == event_id
                ),
                None,
            )
            return {
                "event_id": event_id,
                "base": base,
                "effective": effective_by_id.get(event_id, base),
                "override": overrides_by_id.get(event_id),
                "source_tweet_urls": sorted(split_source_tweet_urls(base)),
                "schedule": schedule,
                "revision": revision,
            }

    def save_override(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = load_manual_event_overrides(self.overrides_json)
            if body.get("revision") != override_revision(current):
                raise ApiError(409, "別のタブで補正データが更新されました。再読み込みしてください。")
            detail = self.event(event_id)
            override = {
                "target_event_id": event_id,
                "target_source_tweet_urls": body.get("target_source_tweet_urls") or detail["source_tweet_urls"],
                "set": body.get("set", {}),
                "note": body.get("note", ""),
                "updated_at": now_iso(),
            }
            updated = upsert_manual_event_override(current, override)
            write_manual_event_overrides(self.overrides_json, updated)
            try:
                rebuild = self.rebuild()
            except Exception:
                write_manual_event_overrides(self.overrides_json, current)
                raise
            return {"event": self.event(event_id), "rebuild": rebuild}

    def delete_override(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = load_manual_event_overrides(self.overrides_json)
            if body.get("revision") != override_revision(current):
                raise ApiError(409, "別のタブで補正データが更新されました。再読み込みしてください。")
            updated = delete_manual_event_override(current, event_id)
            write_manual_event_overrides(self.overrides_json, updated)
            try:
                rebuild = self.rebuild()
            except Exception:
                write_manual_event_overrides(self.overrides_json, current)
                raise
            return {"event": self.event(event_id), "rebuild": rebuild}

    def schedule(self) -> dict[str, Any]:
        with self._lock:
            return self._load_schedule()

    def publish(self) -> dict[str, Any]:
        with self._lock:
            if self.git_status().get("branch") != "main":
                raise ApiError(409, "mainブランチでのみGitHubへ反映できます")
            self._git(["fetch", "origin", "main"])
            behind_text = self._git(["rev-list", "--count", "HEAD..origin/main"]).stdout.strip()
            if int(behind_text or "0") > 0:
                raise ApiError(409, "ローカルのmainがorigin/mainより古いため、先に更新してください")
            override_path = "config/manual_event_overrides.json"
            changed = self._git(["status", "--short", "--", override_path]).stdout.strip()
            if not changed:
                raise ApiError(409, "GitHubへ反映する補正差分がありません")
            self._git(["add", "--", override_path])
            self._git(["commit", "--only", "-m", "Update manual event corrections", "--", override_path])
            self._git(["push", "origin", "HEAD:main"])
            return {"published": True, "commit": self._git(["rev-parse", "HEAD"]).stdout.strip()}


class MaintenanceRequestHandler(BaseHTTPRequestHandler):
    server_version = "TheaterMaintenance/1.0"

    @property
    def service(self) -> MaintenanceService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _allowed_host(self) -> bool:
        port = self.server.server_port
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _check_origin(self) -> None:
        port = self.server.server_port
        origin = self.headers.get("Origin", "")
        if origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            raise ApiError(403, "更新元を確認できません")

    def _json(self, status: int, payload: Any) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "Content-Lengthが不正です") from exc
        if length <= 0 or length > MAX_BODY_SIZE:
            raise ApiError(413, "JSON bodyのサイズが不正です")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "JSON bodyを解釈できません") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON bodyはオブジェクトである必要があります")
        return payload

    def _handle(self, callback: Any) -> None:
        try:
            if not self._allowed_host():
                raise ApiError(403, "Hostを許可できません")
            callback()
        except ApiError as exc:
            self._json(exc.status, {"error": str(exc)})
        except (ManualOverrideError, ArtifactSyncError, FileNotFoundError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "処理中に予期しないエラーが発生しました"})

    def do_GET(self) -> None:
        self._handle(self._do_get)

    def _do_get(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/api/status":
            self._json(200, self.service.status())
            return
        if path == "/api/events":
            self._json(200, self.service.events(parse_qs(parsed.query)))
            return
        if path.startswith("/api/events/"):
            event_id = unquote(path.removeprefix("/api/events/"))
            if "/" in event_id or not event_id:
                raise ApiError(404, "APIが見つかりません")
            self._json(200, self.service.event(event_id))
            return
        if path == "/api/schedule":
            self._json(200, self.service.schedule())
            return
        static_files = {
            "/": "index.html",
            "/index.html": "index.html",
            "/maintenance.js": "maintenance.js",
            "/maintenance.css": "maintenance.css",
        }
        filename = static_files.get(path)
        if filename is None:
            raise ApiError(404, "ページが見つかりません")
        source = STATIC_DIR / filename
        if not source.is_file():
            raise ApiError(404, "画面ファイルが見つかりません")
        body = source.read_bytes()
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self._handle(self._do_post)

    def _do_post(self) -> None:
        self._check_origin()
        path = urlsplit(self.path).path
        if path == "/api/sync":
            self._json(200, self.service.sync())
            return
        if path == "/api/publish":
            self._json(200, self.service.publish())
            return
        raise ApiError(404, "APIが見つかりません")

    def do_PUT(self) -> None:
        self._handle(self._do_put)

    def _do_put(self) -> None:
        self._check_origin()
        path = urlsplit(self.path).path
        prefix = "/api/events/"
        suffix = "/override"
        if not path.startswith(prefix) or not path.endswith(suffix):
            raise ApiError(404, "APIが見つかりません")
        event_id = unquote(path[len(prefix):-len(suffix)]).strip("/")
        if not event_id or "/" in event_id:
            raise ApiError(404, "APIが見つかりません")
        self._json(200, self.service.save_override(event_id, self._read_json()))

    def do_DELETE(self) -> None:
        self._handle(self._do_delete)

    def _do_delete(self) -> None:
        self._check_origin()
        path = urlsplit(self.path).path
        prefix = "/api/events/"
        suffix = "/override"
        if not path.startswith(prefix) or not path.endswith(suffix):
            raise ApiError(404, "APIが見つかりません")
        event_id = unquote(path[len(prefix):-len(suffix)]).strip("/")
        if not event_id or "/" in event_id:
            raise ApiError(404, "APIが見つかりません")
        self._json(200, self.service.delete_override(event_id, self._read_json()))


class MaintenanceHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], service: MaintenanceService):
        super().__init__(address, MaintenanceRequestHandler)
        self.service = service


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ローカル公演メンテナンス画面を起動する")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = MaintenanceHTTPServer(("127.0.0.1", args.port), MaintenanceService())
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"maintenance server: {url}")
    print("終了するには Ctrl+C を押してください")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
