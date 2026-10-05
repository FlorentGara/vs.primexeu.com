from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SCRIPT_DIR = Path(
    r"W:\05_CLIENTS\02_VS\00_TEMPLATE\FILLED\AMAZON\01_WINE-SPIRITS\FINAL\PICTURE"
)
HOST = "127.0.0.1"
PORT = int(os.environ.get("VS_DASHBOARD_PORT", "8765"))


PROGRAMS = [
    {
        "file": "download_photo_vs.py",
        "title": "Excel Product Folder Automator",
        "group": "Excel + Photos",
        "description": "Downloads or organizes product images from Excel sources into destination folders.",
        "needs": "pandas, openpyxl, requests",
    },
    {
        "file": "url_generator.py",
        "title": "LinkGen Pro",
        "group": "URLs",
        "description": "Generates product photo URLs from folders and can monitor/check links.",
        "needs": "pandas, ttkbootstrap, requests optional, tkinterdnd2 optional",
    },
    {
        "file": "photo_organizer.py",
        "title": "Photo Organizer",
        "group": "Photos",
        "description": "Organizes image files through a desktop folder-selection workflow.",
        "needs": "standard Python tkinter",
    },
    {
        "file": "organizerLH.py",
        "title": "Photo Organizer LH",
        "group": "Photos",
        "description": "Alternate photo organizer workflow for LH-style folder processing.",
        "needs": "standard Python tkinter",
    },
    {
        "file": "RENAME_PHOTO.py",
        "title": "Rename Photo",
        "group": "Photos",
        "description": "Renames and processes image files in a selected folder.",
        "needs": "standard Python tkinter",
    },
    {
        "file": "VS_IMAGE_GENERATOR_4x4x4.py",
        "title": "VS Image Generator 4x4x4",
        "group": "Image Generation",
        "description": "Creates bottle grid images in 1, 3, 6, and 12 item layouts.",
        "needs": "Pillow, ttkthemes optional",
    },
    {
        "file": "VS_IMAGE_GENERATOR_4x4x4_FG.py",
        "title": "VS Image Generator 4x4x4 FG",
        "group": "Image Generation",
        "description": "Foreground variant of the bottle grid image generator.",
        "needs": "Pillow, ttkthemes optional",
    },
    {
        "file": "VS_IMAGE_GENERATOR_BIG_BOTTLE.py",
        "title": "VS Image Generator Big Bottle",
        "group": "Image Generation",
        "description": "Creates larger bottle grid compositions for product imagery.",
        "needs": "Pillow, ttkthemes optional",
    },
]

RUNNING: dict[int, subprocess.Popen] = {}
EVENTS: list[dict[str, str]] = []


def program_payload() -> list[dict[str, object]]:
    payload = []
    for idx, program in enumerate(PROGRAMS):
        path = SCRIPT_DIR / str(program["file"])
        item = dict(program)
        item["id"] = idx
        item["path"] = str(path)
        item["exists"] = path.exists()
        item["size"] = path.stat().st_size if path.exists() else 0
        item["modified"] = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
            if path.exists()
            else ""
        )
        item["running"] = idx in RUNNING and RUNNING[idx].poll() is None
        payload.append(item)
    return payload


def add_event(level: str, message: str) -> None:
    EVENTS.insert(
        0,
        {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        },
    )
    del EVENTS[50:]


def open_in_explorer(path: Path) -> None:
    subprocess.Popen(["explorer", "/select,", str(path)])


def launch_program(path: Path) -> None:
    title = path.stem.replace("_", " ")
    command = f'py -3 "{path}"'
    subprocess.Popen(
        ["cmd.exe", "/c", "start", title, "/D", str(path.parent), "cmd.exe", "/k", command],
        cwd=str(path.parent),
    )


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VS Picture Program Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #18212f;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #0f766e;
      --accent-strong: #115e59;
      --warn: #b45309;
      --bad: #b42318;
      --ok: #067647;
      --shadow: 0 12px 36px rgba(16, 24, 40, 0.09);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      letter-spacing: 0;
    }
    .app {
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }
    aside {
      background: #111827;
      color: #f9fafb;
      padding: 22px 16px;
      border-right: 1px solid #0b1220;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 22px;
      padding: 0 6px;
    }
    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: var(--accent);
      font-weight: 700;
    }
    h1 {
      font-size: 18px;
      margin: 0;
      line-height: 1.2;
    }
    .sub {
      color: #a7b0c0;
      font-size: 12px;
      margin-top: 3px;
    }
    .nav-section {
      color: #9ca3af;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      margin: 20px 8px 8px;
    }
    .program-btn {
      width: 100%;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      text-align: left;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: #e5e7eb;
      padding: 10px 9px;
      cursor: pointer;
      font: inherit;
    }
    .program-btn:hover,
    .program-btn.active {
      background: #263244;
    }
    .program-title {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 14px;
      font-weight: 600;
    }
    .pill {
      border: 1px solid #4b5563;
      border-radius: 999px;
      color: #cbd5e1;
      padding: 2px 7px;
      font-size: 11px;
    }
    main {
      padding: 28px;
      overflow: auto;
    }
    .topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 22px;
    }
    h2 {
      margin: 0 0 6px;
      font-size: 26px;
      line-height: 1.15;
    }
    .path {
      font-family: Consolas, "Courier New", monospace;
      color: var(--muted);
      font-size: 13px;
      word-break: break-all;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    button.action {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 10px 13px;
      color: var(--ink);
      cursor: pointer;
      font-weight: 650;
      min-height: 40px;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }
    button.primary:hover { background: var(--accent-strong); }
    button.action:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, .75fr);
      gap: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 18px;
    }
    .panel h3 {
      margin: 0 0 14px;
      font-size: 16px;
    }
    .facts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }
    .fact {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 78px;
    }
    .label {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 5px;
    }
    .value {
      font-weight: 700;
      word-break: break-word;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--muted);
    }
    .ok .dot { background: var(--ok); }
    .bad .dot { background: var(--bad); }
    .run .dot { background: var(--warn); }
    .command {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border: 1px solid var(--line);
      background: #f8fafc;
      border-radius: 8px;
      padding: 12px;
      margin-top: 12px;
    }
    code {
      font-family: Consolas, "Courier New", monospace;
      color: #344054;
      overflow-wrap: anywhere;
    }
    .events {
      display: grid;
      gap: 8px;
      max-height: 330px;
      overflow: auto;
    }
    .event {
      border-left: 4px solid var(--line);
      padding: 9px 10px;
      background: #f8fafc;
      border-radius: 0 8px 8px 0;
      color: #344054;
      font-size: 13px;
    }
    .event.ok { border-color: var(--ok); }
    .event.error { border-color: var(--bad); }
    .event.info { border-color: var(--accent); }
    .empty {
      color: var(--muted);
      font-size: 14px;
    }
    @media (max-width: 860px) {
      .app { grid-template-columns: 1fr; }
      aside { height: auto; position: relative; }
      .grid { grid-template-columns: 1fr; }
      .topbar { flex-direction: column; }
      .actions { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand">
        <div class="mark">VS</div>
        <div>
          <h1>Picture Programs</h1>
          <div class="sub">Amazon Wine-Spirits toolkit</div>
        </div>
      </div>
      <div id="nav"></div>
    </aside>
    <main>
      <div class="topbar">
        <div>
          <h2 id="title"></h2>
          <div class="path" id="path"></div>
        </div>
        <div class="actions">
          <button class="action primary" id="runBtn">Open Program</button>
          <button class="action" id="copyBtn">Copy Command</button>
          <button class="action" id="folderBtn">Show File</button>
          <button class="action" id="refreshBtn">Refresh</button>
        </div>
      </div>
      <div class="grid">
        <section class="panel">
          <h3>Program</h3>
          <p id="description"></p>
          <p class="empty">These Python files are desktop Tkinter programs. The dashboard opens the selected program in a normal Windows app window.</p>
          <span id="status" class="status"><span class="dot"></span><span></span></span>
          <div class="facts">
            <div class="fact"><div class="label">Group</div><div class="value" id="group"></div></div>
            <div class="fact"><div class="label">Dependencies</div><div class="value" id="needs"></div></div>
            <div class="fact"><div class="label">Modified</div><div class="value" id="modified"></div></div>
            <div class="fact"><div class="label">File Size</div><div class="value" id="size"></div></div>
          </div>
          <div class="command">
            <code id="command"></code>
          </div>
        </section>
        <section class="panel">
          <h3>Activity</h3>
          <div class="events" id="events"><div class="empty">No activity yet.</div></div>
        </section>
      </div>
    </main>
  </div>
  <script>
    let programs = [];
    let selected = 0;

    const el = (id) => document.getElementById(id);
    const bytes = (n) => n ? `${(n / 1024).toFixed(1)} KB` : "Missing";

    async function api(path, options) {
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Request failed");
      return data;
    }

    function commandFor(program) {
      return `py -3 "${program.path}"`;
    }

    function renderNav() {
      const grouped = new Map();
      programs.forEach((program) => {
        if (!grouped.has(program.group)) grouped.set(program.group, []);
        grouped.get(program.group).push(program);
      });
      el("nav").innerHTML = "";
      grouped.forEach((items, group) => {
        const heading = document.createElement("div");
        heading.className = "nav-section";
        heading.textContent = group;
        el("nav").appendChild(heading);
        items.forEach((program) => {
          const btn = document.createElement("button");
          btn.className = `program-btn ${program.id === selected ? "active" : ""}`;
          btn.innerHTML = `<span class="program-title">${program.title}</span><span class="pill">${program.running ? "open" : program.exists ? "ready" : "missing"}</span>`;
          btn.onclick = () => { selected = program.id; render(); };
          el("nav").appendChild(btn);
        });
      });
    }

    function renderEvents(events) {
      if (!events.length) {
        el("events").innerHTML = '<div class="empty">No activity yet.</div>';
        return;
      }
      el("events").innerHTML = events.map((event) =>
        `<div class="event ${event.level}"><strong>${event.time}</strong> ${event.message}</div>`
      ).join("");
    }

    function render() {
      const program = programs.find((item) => item.id === selected) || programs[0];
      if (!program) return;
      selected = program.id;
      el("title").textContent = program.title;
      el("path").textContent = program.path;
      el("description").textContent = program.description;
      el("group").textContent = program.group;
      el("needs").textContent = program.needs;
      el("modified").textContent = program.modified || "Missing";
      el("size").textContent = bytes(program.size);
      el("command").textContent = commandFor(program);

      const status = el("status");
      status.className = `status ${program.running ? "run" : program.exists ? "ok" : "bad"}`;
      status.querySelector("span:last-child").textContent = program.running ? "Running" : program.exists ? "Ready" : "File missing";
      el("runBtn").disabled = !program.exists;
      el("folderBtn").disabled = !program.exists;
      renderNav();
    }

    async function refresh() {
      const data = await api("/api/programs");
      programs = data.programs;
      renderEvents(data.events);
      render();
    }

    el("runBtn").onclick = async () => {
      const program = programs.find((item) => item.id === selected);
      await api("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: program.id })
      });
      await refresh();
    };

    el("copyBtn").onclick = async () => {
      const program = programs.find((item) => item.id === selected);
      await navigator.clipboard.writeText(commandFor(program));
    };

    el("folderBtn").onclick = async () => {
      const program = programs.find((item) => item.id === selected);
      await api("/api/show", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: program.id })
      });
      await refresh();
    };

    el("refreshBtn").onclick = refresh;
    refresh();
    setInterval(refresh, 4000);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/programs":
            cleanup_processes()
            self.send_json({"programs": program_payload(), "events": EVENTS})
            return
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            data = self.read_json()
            program_id = int(data.get("id", -1))
            if program_id < 0 or program_id >= len(PROGRAMS):
                self.send_json({"error": "Unknown program"}, 400)
                return
            path = SCRIPT_DIR / str(PROGRAMS[program_id]["file"])
            if not path.exists():
                self.send_json({"error": "Program file is missing"}, 404)
                return
            if route == "/api/run":
                launch_program(path)
                add_event("ok", f"Opened {path.name}.")
                self.send_json({"ok": True})
                return
            if route == "/api/show":
                open_in_explorer(path)
                add_event("info", f"Opened Explorer for {path.name}.")
                self.send_json({"ok": True})
                return
            self.send_json({"error": "Not found"}, 404)
        except Exception as exc:
            add_event("error", str(exc))
            self.send_json({"error": str(exc)}, 500)


def cleanup_processes() -> None:
    finished = [idx for idx, proc in RUNNING.items() if proc.poll() is not None]
    for idx in finished:
        name = PROGRAMS[idx]["file"]
        add_event("info", f"{name} closed.")
        del RUNNING[idx]


def main() -> None:
    if not SCRIPT_DIR.exists():
        raise SystemExit(f"Script folder does not exist: {SCRIPT_DIR}")
    add_event("info", "Dashboard server started.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"VS Picture Program Dashboard: http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
