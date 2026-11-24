#!/usr/bin/env python3
"""Local browser GUI for the LibRead downloader.

Starts a small web server on 127.0.0.1, opens your default browser and lets
you pick chapters to download with a live progress console. The existing
libread package is reused as-is; no native GUI toolkit is required.

Run:
    python3 libread_gui.py                 # port 8902, output 'downloads'
    python3 libread_gui.py --port 9000 -o novels
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from libread.chapter import LockedChapterError
from libread.downloader import DownloadCancelled, download_chapter, download_cover, series_directory
from libread.epub import build_epub
from libread.network import HttpClient
from libread.parser import Series, fetch_series
from libread_dl import extract_slug

MEDIA_ORIGIN = "https://libread.com"
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LibRead Downloader</title>
<style>
:root {
  --bg: #0f1115; --panel: #171a21; --border: #2a2f3a; --text: #e6e9ef;
  --muted: #9aa4b2; --accent: #e04f5f; --ok: #4ade80; --warn: #fbbf24; --err: #f87171;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.wrap { max-width: 880px; margin: 0 auto; padding: 24px 16px 80px; }
h1 { font-size: 22px; margin: 0 0 2px; }
.sub { color: var(--muted); font-size: 13px; margin: 0 0 20px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.label { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin: 0 0 6px; }
.row { display: flex; gap: 8px; align-items: center; }
input[type=text] { flex: 1; background: #0b0d11; border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; padding: 10px 12px; font-size: 14px; outline: none; }
input[type=text]:focus { border-color: var(--accent); }
button { background: var(--accent); color: #fff; border: 0; border-radius: 8px; padding: 10px 16px;
  font-size: 14px; font-weight: 600; cursor: pointer; }
button:hover { filter: brightness(1.12); }
button:disabled { opacity: .45; cursor: not-allowed; }
button.ghost { background: transparent; border: 1px solid var(--border); color: var(--text); }
button.ok { background: #166534; }
.series { display: flex; gap: 16px; align-items: flex-start; }
.cover { flex: none; width: 120px; height: 180px; object-fit: cover; border-radius: 8px;
  border: 1px solid var(--border); background: #0b0d11; }
.info h2 { margin: 0 0 6px; font-size: 18px; }
.stats { display: flex; gap: 12px; flex-wrap: wrap; margin: 8px 0 0; font-size: 13px; color: var(--muted); }
.pill { padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); font-size: 12px; }
.pill.locked { color: var(--warn); border-color: #3a2f16; }
.chapters { max-height: 340px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; margin-top: 12px; }
.ch-row { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-bottom: 1px solid #1c2029; font-size: 13px; }
.ch-row:last-child { border-bottom: 0; }
.ch-row input { accent-color: var(--accent); }
.ch-row .title { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ch-row .num { color: var(--muted); font-size: 11px; min-width: 42px; text-align: right; }
.ch-row.locked .title { color: var(--muted); }
.tools { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 12px; }
.tools input[type=text] { flex: none; width: 130px; }
.count { margin-left: auto; color: var(--muted); font-size: 13px; }
#progress-card { display: none; }
.pstatus { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.badge { font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 999px; text-transform: uppercase; }
.badge.running { background: #312e1b; color: var(--warn); }
.badge.done { background: #14331f; color: var(--ok); }
.badge.cancelled { background: #33201f; color: var(--err); }
.badge.error { background: #33201f; color: var(--err); }
.bar-wrap { height: 12px; background: #0b0d11; border-radius: 999px; overflow: hidden; }
.bar { height: 100%; width: 0; background: linear-gradient(90deg, var(--accent), #ff8a5c); transition: width .25s; }
.plabel { font-size: 13px; color: var(--muted); margin: 8px 0 0; font-family: ui-monospace, monospace; }
.console { margin-top: 12px; background: #0b0d11; border: 1px solid var(--border); border-radius: 8px;
  padding: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
  line-height: 1.5; height: 260px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }
.console .err { color: var(--err); }
.hidden { display: none; }
#toast { display: none; position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
  background: #33201f; color: #fff; padding: 10px 16px; border-radius: 8px; border: 1px solid var(--err); font-size: 13px; z-index: 10; }
</style>
</head>
<body>
<div id="toast"></div>
<div class="wrap">
  <h1>LibRead Downloader</h1>
  <p class="sub">Download covers and chapters from libread.com</p>

  <div class="card">
    <p class="label">Series URL or slug</p>
    <div class="row">
      <input type="text" id="url-input" placeholder="https://libread.com/libread/... or just-the-slug"
             value="">
      <button id="load-btn" onclick="loadSeries()">Load</button>
    </div>
  </div>

  <div class="card hidden" id="series-card">
    <div class="series">
      <img class="cover" id="cover" alt="cover">
      <div class="info">
        <h2 id="title"></h2>
        <div class="stats" id="stats"></div>
        <div class="chapters" id="chapters"></div>
        <div class="tools">
          <button class="ghost" id="sel-all" onclick="selectAll(true)">Select all</button>
          <button class="ghost" onclick="selectAll(false)">Clear</button>
          <input type="text" id="range-input" placeholder="range e.g. 1-5">
          <button class="ghost" onclick="applyRange()">Apply</button>
          <span class="count" id="count">0 selected</span>
        </div>
      </div>
    </div>
    <div style="margin-top:14px">
      <label style="display:flex;gap:8px;align-items:center;font-size:13px;color:var(--muted);margin-bottom:10px">
        <input type="checkbox" id="no-cover"> Skip cover image
      </label>
      <label style="display:flex;gap:8px;align-items:center;font-size:13px;color:var(--muted);margin-bottom:10px">
        <input type="checkbox" id="no-epub"> Skip EPUB creation
      </label>
      <button id="download-btn" onclick="startDownload()" disabled>Download selected</button>
      <button class="ghost hidden" id="stop-btn" onclick="cancelJob()">Stop</button>
    </div>
  </div>

  <div class="card" id="progress-card">
    <p class="label">Progress</p>
    <div class="pstatus">
      <span class="badge" id="pbadge">idle</span>
      <span class="plabel" id="plabel"></span>
    </div>
    <div class="bar-wrap"><div class="bar" id="bar"></div></div>
    <div class="console" id="console"></div>
  </div>
</div>

<script>
let series = null;
let jobId = null;
let pollTimer = null;

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 4000);
}

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}

async function loadSeries() {
  const btn = document.getElementById('load-btn');
  const url = document.getElementById('url-input').value.trim();
  if (!url) { toast('Enter a series URL'); return; }
  btn.disabled = true; btn.textContent = 'Loading...';
  try {
    const data = await post('/api/series', { url });
    series = data.series;
    renderSeries(series);
  } catch (err) {
    toast('Load failed: ' + err.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Load';
  }
}

function renderSeries(s) {
  document.getElementById('series-card').classList.remove('hidden');
  document.getElementById('title').textContent = s.title;
  document.getElementById('cover').src = s.cover || 'data:image/gif;base64,R0lGODlhAQABAAAAACw=';
  document.getElementById('stats').innerHTML =
    '<span class="pill">' + s.total + ' total</span>' +
    '<span class="pill" style="color:var(--ok)">' + s.accessible + ' accessible</span>' +
    '<span class="pill locked">' + (s.total - s.accessible) + ' locked</span>';
  const box = document.getElementById('chapters');
  box.innerHTML = '';
  let pos = 0;
  for (const ch of s.chapters) {
    const row = document.createElement('div');
    row.className = 'ch-row' + (ch.locked ? ' locked' : '');
    if (!ch.locked) { pos += 1; }
    const num = ch.locked ? '' : pos;
    const title = ch.locked ? ch.title + ' &#128274;' : ch.title;
    row.innerHTML = (ch.locked
      ? '<span class="num"></span><span class="title">' + title + '</span>'
      : '<span class="num">' + num + '</span>' +
        '<input type="checkbox" data-id="' + ch.id + '">' +
        '<span class="title">' + title + '</span>');
    box.appendChild(row);
  }
  updateCount();
  document.getElementById('download-btn').disabled = false;
}

function selectedIds() {
  return [...document.querySelectorAll('.ch-row input[type=checkbox]:checked')]
    .map(el => parseInt(el.dataset.id, 10));
}

function updateCount() {
  const n = selectedIds().length;
  document.getElementById('count').textContent = n + ' selected';
  document.getElementById('download-btn').textContent =
    'Download selected' + (n ? ' (' + n + ')' : '');
  document.getElementById('download-btn').disabled = n === 0;
}

function selectAll(value) {
  document.querySelectorAll('.ch-row input[type=checkbox]')
    .forEach(el => el.checked = value);
  updateCount();
}

function applyRange() {
  const raw = document.getElementById('range-input').value.trim().toLowerCase();
  const boxes = [...document.querySelectorAll('.ch-row input[type=checkbox]')];
  const n = boxes.length;
  if (!raw) return;
  let a = 1, b = 1;
  if (raw === 'all' || raw === '*') { a = 1; b = n; }
  else if (/^\d+$/.test(raw)) { a = parseInt(raw, 10); b = a; }
  else {
    const m = raw.match(/^(\d+)\s*-\s*(\d+)$/);
    if (!m) { toast('Use e.g. 1-5 or all'); return; }
    a = parseInt(m[1], 10); b = parseInt(m[2], 10);
  }
  if (a > b) { toast('Range start must be <= end'); return; }
  boxes.forEach((el, i) => {
    const p = i + 1;
    el.checked = p >= a && p <= b;
  });
  updateCount();
}

async function startDownload() {
  const ids = selectedIds();
  if (!ids.length) { toast('Select at least one chapter'); return; }
  const url = document.getElementById('url-input').value.trim();
  const noCover = document.getElementById('no-cover').checked;
  const noEpub = document.getElementById('no-epub').checked;
  try {
    const data = await post('/api/download', {
      url, chapter_ids: ids, no_cover: noCover, no_epub: noEpub,
    });
    jobId = data.job_id;
    document.getElementById('progress-card').style.display = 'block';
    document.getElementById('download-btn').disabled = true;
    document.getElementById('stop-btn').classList.remove('hidden');
    setBadge('running', 'running');
    const consoleEl = document.getElementById('console');
    consoleEl.innerHTML = '';
    pollTimer = setInterval(pollJob, 700);
  } catch (err) {
    toast('Download failed to start: ' + err.message);
  }
}

async function cancelJob() {
  try { await post('/api/job/' + jobId + '/cancel', {}); }
  catch (err) { toast(err.message); }
}

async function pollJob() {
  if (!jobId) return;
  let snap;
  try {
    const res = await fetch('/api/job/' + jobId);
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
    snap = data;
  } catch (err) {
    toast('Polling failed: ' + err.message);
    stopPolling();
    setBadge('error', 'error');
    return;
  }
  document.getElementById('bar').style.width = snap.progress + '%';
  document.getElementById('plabel').textContent = snap.label || '';
  const consoleEl = document.getElementById('console');
  const prev = consoleEl.textContent;
  const logText = (snap.log || []).join('\n');
  if (logText !== prev) {
    consoleEl.textContent = logText;
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
  if (['done', 'cancelled', 'error'].includes(snap.status)) {
    stopPolling();
    setBadge(snap.status, snap.status);
    document.getElementById('download-btn').disabled = false;
    document.getElementById('stop-btn').classList.add('hidden');
  }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function setBadge(text, cls) {
  const el = document.getElementById('pbadge');
  const allowed = ['running', 'done', 'cancelled', 'error'];
  el.textContent = text;
  el.className = 'badge ' + (allowed.includes(cls) ? cls : 'cancelled');
}

document.getElementById('url-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') loadSeries();
});
document.getElementById('range-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') applyRange();
});
document.addEventListener('change', updateCount);
</script>
</body>
</html>
"""


class DownloadJob:
    """Runs a set of chapter downloads in the background, feeding a GUI."""

    def __init__(self, series: Series, chapter_ids, output_root: str, delay: float, no_cover: bool, no_epub: bool):
        self.id = uuid.uuid4().hex[:10]
        self.series = series
        id_set = set(chapter_ids)
        self.selected = [c for c in series.accessible if c.chapter_id in id_set]
        self.output_root = output_root
        self.delay = delay
        self.no_cover = no_cover
        self.no_epub = no_epub
        self.status = "running"
        self.log: list[str] = []
        self.label = "Queued"
        self.progress = 0.0
        self.chapters_done = 0
        self.image = None
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=f"libread-job-{self.id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self.cancelled.set()

    def notify(self, event: str, **payload) -> None:
        with self._lock:
            if event == "log":
                self.log.append(str(payload.get("text", "")))
            elif event == "chapter":
                self.label = f"Chapter {payload.get('index')} - {payload.get('title')}"
                self.image = None
            elif event == "image":
                self.image = (payload.get("page", 1), payload.get("total", 1))
            self._recalc()

    def _recalc(self) -> None:
        total = max(1, len(self.selected))
        fraction = 0.0
        if self.image is not None:
            page, page_total = self.image
            fraction = (page - 1) / page_total if page_total else 0.0
        self.progress = min(100.0, round(100.0 * (self.chapters_done + fraction) / total, 1))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "progress": self.progress,
                "label": self.label,
                "log": self.log[-400:],
                "chapters_done": self.chapters_done,
                "chapters_total": len(self.selected),
            }

    def _run(self) -> None:
        client = HttpClient()
        try:
            cover_path = None
            if not self.cancelled.is_set() and not self.no_cover:
                self.label = "Downloading cover image..."
                cover_path = download_cover(client, self.series, self.output_root, notify=self.notify)
            done_chapters: list[tuple[int, str]] = []
            total = len(self.selected)
            for position, chapter in enumerate(self.selected, start=1):
                if self.cancelled.is_set():
                    break
                self.notify("log", text="")
                try:
                    list_index = self.series.accessible.index(chapter) + 1
                    download_chapter(
                        client,
                        chapter,
                        self.output_root,
                        self.series,
                        list_index,
                        position,
                        total,
                        delay=self.delay,
                        notify=self.notify,
                        cancel_event=self.cancelled,
                    )
                    self.chapters_done += 1
                    done_chapters.append((list_index, chapter.title))
                except DownloadCancelled:
                    break
                except LockedChapterError as exc:
                    self.notify("log", text=f"[{position}/{total}] SKIP {chapter.title!r}: {exc}")
                except Exception as exc:
                    self.notify("log", text=f"[{position}/{total}] ERROR chapter: {exc}")
                with self._lock:
                    self._recalc()
            if self.cancelled.is_set():
                self.status = "cancelled"
                self.label = "Stopped by user"
                return
            if not self.no_epub and done_chapters:
                self.label = "Building EPUB..."
                self.notify("log", text=f"[epub] building '{self.series.title}.epub' from {len(done_chapters)} chapter(s) ...")
                try:
                    folder = series_directory(self.output_root, self.series)
                    epub_path = build_epub(
                        done_chapters,
                        folder,
                        self.series.title,
                        self.series.slug,
                        author=self.series.author,
                        cover_path=cover_path,
                    )
                    self.notify("log", text=f"  -> {os.path.relpath(epub_path, self.output_root)}")
                except Exception as exc:
                    self.notify("log", text=f"  ! EPUB build failed: {exc}")
            self.status = "done"
            self.label = "Complete"
            self.progress = 100.0
        except Exception as exc:
            self.status = "error"
            self.label = "Error"
            self.notify("log", text=f"FATAL: {exc}")


class AppState:
    def __init__(self, output_root: str, delay: float):
        self.output_root = output_root
        self.delay = delay
        self.jobs: dict[str, DownloadJob] = {}
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "LibReadDownloader/1.0"
    state: AppState

    def log_message(self, fmt, *args):
        pass

    # -- helpers ------------------------------------------------------------

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _get_job(self, job_id: str):
        with self.server.state.lock:
            return self.server.state.jobs.get(job_id)

    # -- routes -------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/proxy":
            self._serve_proxy()
        elif path.startswith("/api/job/"):
            job = self._get_job(path.rsplit("/", 1)[-1])
            if job is None:
                self._send_json({"ok": False, "error": "job not found"}, 404)
            else:
                snap = job.snapshot()
                snap["ok"] = True
                self._send_json(snap)
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/series":
            self._handle_series()
        elif path == "/api/download":
            self._handle_download()
        elif path.startswith("/api/job/"):
            parts = path.split("/")
            job = self._get_job(parts[3]) if len(parts) >= 4 else None
            if job is None:
                self._send_json({"ok": False, "error": "job not found"}, 404)
                return
            action = parts[4] if len(parts) >= 5 else ""
            if action == "cancel":
                job.cancel()
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False, "error": "unknown job action"}, 404)
        else:
            self._send_json({"ok": False, "error": "not found"}, 404)

    # -- handlers -----------------------------------------------------------

    def _handle_series(self):
        try:
            data = self._read_json()
            slug = extract_slug(str(data.get("url", "")))
            client = HttpClient()
            series = fetch_series(slug, client)
            cover = None
            if series.cover_url:
                cover = "/proxy?" + urlencode({"url": series.cover_url})
            chapters = [
                {"id": c.chapter_id, "title": c.title, "locked": c.is_locked}
                for c in series.chapters
            ]
            self._send_json({
                "ok": True,
                "series": {
                    "slug": series.slug,
                    "title": series.title,
                    "cover": cover,
                    "total": len(series.chapters),
                    "accessible": len(series.accessible),
                    "chapters": chapters,
                },
            })
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)

    def _handle_download(self):
        try:
            data = self._read_json()
            slug = extract_slug(str(data.get("url", "")))
            chapter_ids = [int(x) for x in data.get("chapter_ids") or []]
            if not chapter_ids:
                raise ValueError("no chapters selected")
            client = HttpClient()
            series = fetch_series(slug, client)
            job = DownloadJob(
                series,
                chapter_ids,
                self.server.state.output_root,
                self.server.state.delay,
                bool(data.get("no_cover")),
                bool(data.get("no_epub")),
            )
            if not job.selected:
                raise ValueError("no accessible chapters match the selection")
            with self.server.state.lock:
                self.server.state.jobs[job.id] = job
            job.start()
            self._send_json({"ok": True, "job_id": job.id})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)

    def _serve_proxy(self):
        query = parse_qs(urlparse(self.path).query)
        url = (query.get("url") or [""])[0]
        if not url.startswith(MEDIA_ORIGIN + "/"):
            self._send_json({"ok": False, "error": "proxy target not allowed"}, 400)
            return
        try:
            response = requests.get(url, headers={
                "User-Agent": HttpClient().session.headers["User-Agent"],
                "Referer": "https://libread.com/",
            }, timeout=30)
            if response.status_code >= 400:
                self._send_json({"ok": False, "error": f"upstream status {response.status_code}"},
                                response.status_code)
                return
            body = response.content
            self.send_response(200)
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 502)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="libread_gui.py",
        description="Run the LibRead downloader web GUI (opens in your browser).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8902, help="bind port (default: 8902)")
    parser.add_argument("-o", "--output", default="downloads", help="output folder (default: downloads)")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds between chapters (default: 0.3)")
    parser.add_argument("--no-epub", action="store_true", help="disable EPUB creation (default: on)")
    parser.add_argument("--no-browser", action="store_true", help="do not auto-open the browser")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    state = AppState(args.output, args.delay)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.state = state
    port = server.server_address[1]
    url = f"http://{args.host}:{port}"
    print(f"LibRead downloader GUI -> {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
