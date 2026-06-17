#!/usr/bin/env python3
"""Local board server. Source of truth = data/jobs.json + data/state.json.

Run:  python3 scripts/serve.py   (then open http://127.0.0.1:8000)

Serves the board rendered live from jobs.json + state.json, and exposes a tiny
JSON API the board's buttons call so decisions land straight in state.json --
one store, no localStorage, nothing to reconcile.

Endpoints
  GET  /                          -> board HTML (rendered fresh each request)
  GET  /table                     -> compact, sortable table view of the same roles
  GET  /prep/{role-id}            -> rendered interview-prep pack page (or a friendly
                                     "not generated yet" page)
  POST /api/decision              {id, status} -> write status to state.json
  POST /api/queue-cover-letter    {id}         -> append to data/queue/cover-letters.json
  POST /api/queue-interview-prep  {id}         -> append to data/queue/interview-prep.json
  POST /api/reset                              -> clear all decisions in state.json

Stdlib only. The handlers are deliberately small/pure so they port cleanly to
AWS Lambda + API Gateway later if this ever moves off the laptop.
"""
import json
import os
import sys
import tempfile
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import render_html, render_table_html, render_prep_page, load_json, DATA  # noqa: E402
from urllib.parse import unquote  # noqa: E402

HOST = os.environ.get("BOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("BOARD_PORT", "8000"))

VALID_STATUSES = {"new", "applied", "interviewing", "rejected", "offer", "hidden"}
STATE_PATH = DATA / "state.json"
JOBS_PATH = DATA / "jobs.json"
QUEUE_PATH = DATA / "queue" / "cover-letters.json"          # cover-letter requests
QUEUE_PREP_PATH = DATA / "queue" / "interview-prep.json"   # interview-prep requests


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def atomic_write_json(path, obj):
    """Write JSON atomically (temp file + os.replace) so a crash mid-write
    can never corrupt the source of truth."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def update_decision(role_id, status):
    state = load_json(STATE_PATH, {"schemaVersion": 1, "jobs": {}})
    state.setdefault("jobs", {})
    state["jobs"][role_id] = {"status": status, "updatedAt": now_iso()}
    atomic_write_json(STATE_PATH, state)
    return state


def reset_state():
    state = load_json(STATE_PATH, {"schemaVersion": 1, "jobs": {}})
    state["jobs"] = {}
    atomic_write_json(STATE_PATH, state)
    return state


def _enqueue(role_id, queue_path):
    """Append a role to a request queue (cover letter or interview prep), dedup while
    pending. Returns the number of still-pending requests in that queue."""
    jobs = load_json(JOBS_PATH, {"roles": []})
    role = next((r for r in jobs.get("roles", []) if r.get("id") == role_id), None)
    if role is None:
        raise KeyError(f"unknown role id: {role_id}")

    queue = load_json(queue_path, {"schemaVersion": 1, "requests": []})
    queue.setdefault("requests", [])
    # Don't double-queue a role that's still pending.
    pending = {q["id"] for q in queue["requests"] if q.get("status") == "pending"}
    if role_id not in pending:
        queue["requests"].append({
            "id": role_id,
            "company": role.get("company"),
            "title": role.get("title"),
            "url": role.get("atsUrl") or role.get("sourceUrl") or role.get("url"),
            "requestedAt": now_iso(),
            "status": "pending",
        })
        atomic_write_json(queue_path, queue)
    return sum(1 for q in queue["requests"] if q.get("status") == "pending")


def queue_cover_letter(role_id):
    return _enqueue(role_id, QUEUE_PATH)


def queue_interview_prep(role_id):
    return _enqueue(role_id, QUEUE_PREP_PATH)


class Handler(BaseHTTPRequestHandler):
    server_version = "JobBoard/1.0"

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def log_message(self, fmt, *args):  # quieter logging
        sys.stderr.write("[board] " + (fmt % args) + "\n")

    def do_GET(self):
        # Board/Table cross-links carry filter state in the query string; route on
        # the path only.
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            jobs = load_json(JOBS_PATH, {"roles": []})
            state = load_json(STATE_PATH, {"jobs": {}})
            self._send(200, render_html(jobs, state), ctype="text/html")
        elif path == "/table":
            jobs = load_json(JOBS_PATH, {"roles": []})
            state = load_json(STATE_PATH, {"jobs": {}})
            self._send(200, render_table_html(jobs, state), ctype="text/html")
        elif path.startswith("/prep/"):
            role_id = unquote(path[len("/prep/"):]).strip("/")
            code, page = render_prep_page(role_id)
            self._send(code, page, ctype="text/html")
        elif path == "/favicon.ico":
            self._send(204, b"", ctype="image/x-icon")
        elif path == "/api/state":
            self._send(200, load_json(STATE_PATH, {"jobs": {}}))
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/api/decision":
                payload = self._read_json()
                rid, status = payload.get("id"), payload.get("status")
                if not rid or status not in VALID_STATUSES:
                    return self._send(400, {"error": "id and valid status required"})
                update_decision(rid, status)
                return self._send(200, {"ok": True, "id": rid, "status": status})

            if self.path == "/api/queue-cover-letter":
                payload = self._read_json()
                rid = payload.get("id")
                if not rid:
                    return self._send(400, {"error": "id required"})
                n = queue_cover_letter(rid)
                return self._send(200, {"ok": True, "queued": n})

            if self.path == "/api/queue-interview-prep":
                payload = self._read_json()
                rid = payload.get("id")
                if not rid:
                    return self._send(400, {"error": "id required"})
                n = queue_interview_prep(rid)
                return self._send(200, {"ok": True, "queued": n})

            if self.path == "/api/reset":
                reset_state()
                return self._send(200, {"ok": True})

            self._send(404, {"error": "not found"})
        except KeyError as e:
            self._send(404, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Job board running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    print(f"  source of truth: {JOBS_PATH}  +  {STATE_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
