from __future__ import annotations

import importlib.util
import os
import re
import requests
import shutil
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, Response, flash, jsonify, redirect, render_template_string, request, send_from_directory, url_for


DEFAULT_ROOT = r"W:\05_CLIENTS\02_VS\00_TEMPLATE\FILLED\AMAZON\01_WINE-SPIRITS\FINAL\PICTURE"
SERVER_ROOT = Path(os.environ.get("VS_FILE_ROOT", DEFAULT_ROOT)).resolve()
BROWSE_ROOT = Path(os.environ.get("VS_BROWSE_ROOT", str(SERVER_ROOT))).resolve()
SCRIPT_ROOT = Path(os.environ.get("VS_SCRIPT_ROOT", DEFAULT_ROOT)).resolve()
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}
ALLOWED_URL_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}

app = Flask(__name__)
app.secret_key = os.environ.get("VS_DASHBOARD_SECRET", "change-me-on-server")


@dataclass
class Result:
    title: str
    summary: str
    rows: list[dict[str, Any]]


def resolve_server_path(raw: str) -> Path:
    value = raw.strip().strip('"')
    if not value:
        raise ValueError("Path is required.")
    path = Path(value)
    if not path.is_absolute():
        path = SERVER_ROOT / value
    return path.resolve()


def ensure_dir(path: Path, label: str) -> None:
    if not path.exists():
        raise ValueError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"{label} is not a folder: {path}")


def is_under_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(BROWSE_ROOT)
        return True
    except ValueError:
        return False


def number_sort_key(path: Path | str) -> tuple[int, str]:
    name = path.name if isinstance(path, Path) else str(path)
    match = re.search(r"(\d+)", name)
    return (int(match.group(1)) if match else 10**12, name.lower())


def check_url_status(url: str) -> str:
    try:
        response = requests.head(url, allow_redirects=True, timeout=8)
        if response.status_code in {403, 405}:
            response = requests.get(url, stream=True, allow_redirects=True, timeout=8)
        return f"{response.status_code} {response.reason}"
    except Exception as exc:
        return f"ERROR: {exc}"


def generate_urls(base_url: str, folder_paths: list[Path], include_subfolders: bool, check_urls: bool = False) -> Result:
    if not base_url.strip():
        raise ValueError("Base URL is required.")
    base_url = base_url.strip()
    if not base_url.endswith("/"):
        base_url += "/"

    targets: list[Path] = []
    for folder in folder_paths:
        ensure_dir(folder, "Folder")
        if include_subfolders:
            targets.extend(sorted([p for p in folder.iterdir() if p.is_dir()], key=number_sort_key))
        else:
            targets.append(folder)

    rows: list[dict[str, Any]] = []
    for folder in targets:
        folder_name = folder.name
        for file_path in sorted(folder.iterdir(), key=number_sort_key):
            if file_path.is_file() and file_path.suffix.lower() in ALLOWED_URL_EXTENSIONS:
                encoded_file = urllib.parse.quote(file_path.name)
                rows.append(
                    {
                        "folder": folder_name,
                        "file": file_path.name,
                        "url": f"{base_url}{urllib.parse.quote(folder_name)}/{encoded_file}",
                    }
                )
                if check_urls:
                    rows[-1]["status"] = check_url_status(rows[-1]["url"])
    return Result("Generated URLs", f"Generated {len(rows)} URL(s) from {len(targets)} folder(s).", rows)


def rename_artikelbild(source: Path) -> Result:
    ensure_dir(source, "Source folder")
    output = source / "Renamed_Photos"
    output.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    for file_path in sorted(source.iterdir(), key=number_sort_key):
        if file_path.is_file() and "Artikelbild" in file_path.name:
            match = re.search(r"(\d+)", file_path.name)
            if not match:
                continue
            destination = output / f"{match.group(1)}{file_path.suffix}"
            shutil.copy2(file_path, destination)
            rows.append({"source": file_path.name, "destination": str(destination)})
    return Result("Rename Photos", f"Copied {len(rows)} image(s) into {output}.", rows)


def organize_photos(source: Path, destination: Path) -> Result:
    ensure_dir(source, "Source folder")
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    skipped = 0
    for file_path in sorted(source.iterdir(), key=number_sort_key):
        if not file_path.is_file() or file_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
            continue
        code = file_path.stem.split("_")[0]
        if not code.isdigit():
            skipped += 1
            continue
        folder = destination / code
        folder.mkdir(exist_ok=True)
        target = folder / file_path.name
        shutil.copy2(file_path, target)
        rows.append({"source": file_path.name, "destination": str(target)})
    return Result("Photo Organizer", f"Copied {len(rows)} image(s). Skipped {skipped}.", rows)


def load_grid_module(variant: str):
    files = {
        "standard": "VS_IMAGE_GENERATOR_4x4x4.py",
        "fg": "VS_IMAGE_GENERATOR_4x4x4_FG.py",
        "big": "VS_IMAGE_GENERATOR_BIG_BOTTLE.py",
    }
    file_name = files.get(variant, files["standard"])
    module_path = SCRIPT_ROOT / file_name
    if not module_path.exists():
        raise ValueError(f"Generator script is missing: {module_path}")
    spec = importlib.util.spec_from_file_location(f"vs_grid_{variant}", module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load generator: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_grids(parent: Path, quantities: list[str], export_format: str, variant: str, delete_original: bool) -> Result:
    ensure_dir(parent, "Parent folder")
    if not quantities:
        raise ValueError("Select at least one quantity.")
    if export_format not in {"png", "jpg"}:
        raise ValueError("Export format must be png or jpg.")

    module = load_grid_module(variant)
    image_exts = tuple(getattr(module, "VALID_IMAGE_EXTENSIONS", (".png", ".jpg", ".jpeg")))
    rows: list[dict[str, Any]] = []
    errors = 0

    for subfolder in sorted([p for p in parent.iterdir() if p.is_dir()], key=number_sort_key):
        for image_path in sorted(subfolder.iterdir(), key=number_sort_key):
            if not image_path.is_file() or image_path.suffix.lower() not in image_exts:
                continue
            source_img = None
            saved = 0
            try:
                source_img = module.Image.open(image_path).convert("RGBA")
                for quantity in quantities:
                    out_name = f"{quantity.replace('_alt', '-alt')}.{export_format}"
                    out_path = subfolder / out_name
                    result_img = module.generate_composited_grid(source_img, quantity)
                    if export_format == "jpg":
                        result_img.convert("RGB").save(out_path, quality=95, optimize=True)
                    else:
                        result_img.save(out_path, optimize=True)
                    saved += 1
                    rows.append({"folder": subfolder.name, "source": image_path.name, "created": str(out_path)})
                if delete_original and saved == len(quantities):
                    if source_img:
                        source_img.close()
                        source_img = None
                    image_path.unlink()
            except Exception as exc:
                errors += 1
                rows.append({"folder": subfolder.name, "source": image_path.name, "error": str(exc)})
            finally:
                if source_img:
                    source_img.close()

    return Result("Image Grid Generator", f"Created {sum(1 for r in rows if 'created' in r)} grid image(s). Errors: {errors}.", rows)


BASE_TEMPLATE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VS Picture Web Dashboard</title>
  <link rel="icon" type="image/png" href="{{ url_for('static', filename='logoprimexeu.png') }}">
  <style>
    :root{--bg:#f5f7fa;--panel:#fff;--line:#d8dee8;--ink:#111827;--muted:#667085;--accent:#0f766e;--accent2:#1d4ed8;--danger:#b42318}
    *{box-sizing:border-box} body{margin:0;font-family:"Segoe UI",Arial,sans-serif;background:var(--bg);color:var(--ink);letter-spacing:0}
    .app{display:grid;grid-template-columns:300px 1fr;min-height:100vh}.side{background:#111827;color:white;padding:22px 16px}.brand-wrap{display:grid;gap:12px;margin-bottom:18px}.logo-row{display:flex;align-items:center}.brand-logo{display:block;object-fit:contain}.brand-logo.primex{max-width:228px;max-height:64px}.brand{font-weight:800;font-size:20px;margin-bottom:4px}.root{font-size:12px;color:#a7b0c0;word-break:break-all;margin-bottom:24px}
    .nav a{display:block;color:#e5e7eb;text-decoration:none;padding:11px 10px;border-radius:8px;margin:5px 0;font-weight:650}.nav a.active,.nav a:hover{background:#263244}
    main{padding:28px;max-width:1320px}.top{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:18px}h1{font-size:28px;margin:0 0 5px}.hint{color:var(--muted);font-size:14px;line-height:1.45}
    .panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;margin-bottom:16px;box-shadow:0 10px 28px rgba(16,24,40,.07)}
    .form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.field{display:grid;gap:7px}.field.full{grid-column:1/-1}label{font-weight:700;font-size:13px}
    input,textarea,select{width:100%;border:1px solid var(--line);border-radius:8px;padding:10px 11px;font:inherit;background:white}textarea{min-height:120px;resize:vertical;font-family:Consolas,monospace}
    .checks{display:flex;gap:14px;flex-wrap:wrap}.check{display:flex;align-items:center;gap:7px}.check input{width:auto}
    button,.button{border:0;background:var(--accent);color:white;border-radius:8px;padding:11px 15px;font-weight:750;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;min-height:42px}
    .secondary{background:var(--accent2)}.muted{background:#475467}.danger{background:var(--danger)}
    .messages{display:grid;gap:8px;margin-bottom:14px}.msg{border-left:4px solid var(--accent);background:#eef7f5;padding:10px 12px;border-radius:0 8px 8px 0}
    table{width:100%;border-collapse:collapse;background:white;border:1px solid var(--line);border-radius:8px;overflow:hidden}th,td{text-align:left;border-bottom:1px solid var(--line);padding:9px 10px;font-size:13px;vertical-align:top}th{background:#f8fafc}td{word-break:break-word}
    .copybox{font-family:Consolas,monospace;white-space:pre-wrap;background:#0b1220;color:#e5e7eb;border-radius:8px;padding:12px;max-height:320px;overflow:auto}
    .inline-input{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:start}.browse-btn{background:#475467;white-space:nowrap}
    .modal{position:fixed;inset:0;background:rgba(15,23,42,.45);display:none;align-items:center;justify-content:center;padding:24px;z-index:20}.modal.open{display:flex}
    .dialog{background:white;border-radius:8px;border:1px solid var(--line);box-shadow:0 24px 80px rgba(0,0,0,.24);width:min(860px,96vw);max-height:86vh;display:grid;grid-template-rows:auto auto 1fr auto}
    .dialog-head,.dialog-actions{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center;justify-content:space-between}.dialog-actions{border-top:1px solid var(--line);border-bottom:0}
    .folder-path{font-family:Consolas,monospace;font-size:13px;color:var(--muted);word-break:break-all;padding:12px 16px;background:#f8fafc;border-bottom:1px solid var(--line)}
    .folder-list{overflow:auto;padding:8px}.folder-row{display:flex;align-items:center;gap:10px;width:100%;border:0;background:white;color:var(--ink);text-align:left;padding:10px;border-radius:8px;cursor:pointer;font:inherit}.folder-row:hover{background:#eef2f7}.folder-row.parent{color:var(--accent2);font-weight:700}
    @media(max-width:900px){.app{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.side{position:relative}}
  </style>
</head>
<body>
  <div class="app">
    <aside class="side">
      <div class="brand-wrap">
        <div class="logo-row">
          <img class="brand-logo primex" src="{{ url_for('static', filename='logoprimexeu.png') }}" alt="Primex EU logo">
        </div>
        <div class="brand">VS Picture Web</div>
      </div>
      <div class="root">Work root: {{ server_root }}</div>
      <div class="root">Browse root: {{ browse_root }}</div>
      <nav class="nav">
        {% for key, item in nav.items() %}
          <a class="{{ 'active' if active == key else '' }}" href="{{ url_for('tool_page', tool=key) }}">{{ item }}</a>
        {% endfor %}
      </nav>
    </aside>
    <main>
      {% with messages = get_flashed_messages() %}
        {% if messages %}<div class="messages">{% for message in messages %}<div class="msg">{{ message }}</div>{% endfor %}</div>{% endif %}
      {% endwith %}
      {{ content|safe }}
    </main>
  </div>
  <div class="modal" id="folderModal" aria-hidden="true">
    <div class="dialog">
      <div class="dialog-head"><strong>Choose Server Folder</strong><button type="button" class="muted" id="folderClose">Close</button></div>
      <div class="folder-path" id="folderPath"></div>
      <div class="folder-list" id="folderList"></div>
      <div class="dialog-actions"><span class="hint">Browse starts from the configured browse root.</span><button type="button" id="folderSelect">Use This Folder</button></div>
    </div>
  </div>
  <script>
    let activeFolderTarget = null;
    let currentFolderPath = "";

    async function loadFolders(path) {
      const url = "/api/folders" + (path ? "?path=" + encodeURIComponent(path) : "");
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) {
        alert(data.error || "Could not load folders");
        return;
      }
      currentFolderPath = data.path;
      document.getElementById("folderPath").textContent = data.path;
      const list = document.getElementById("folderList");
      list.innerHTML = "";
      if (data.parent) {
        const parent = document.createElement("button");
        parent.type = "button";
        parent.className = "folder-row parent";
        parent.textContent = "Up one folder";
        parent.onclick = () => loadFolders(data.parent);
        list.appendChild(parent);
      }
      if (!data.folders.length) {
        const empty = document.createElement("div");
        empty.className = "hint";
        empty.style.padding = "14px";
        empty.textContent = "No subfolders here.";
        list.appendChild(empty);
      }
      data.folders.forEach((folder) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "folder-row";
        row.textContent = folder.name;
        row.onclick = () => loadFolders(folder.path);
        list.appendChild(row);
      });
    }

    document.querySelectorAll("[data-browse-for]").forEach((button) => {
      button.addEventListener("click", () => {
        activeFolderTarget = document.querySelector(button.dataset.browseFor);
        document.getElementById("folderModal").classList.add("open");
        const value = activeFolderTarget && activeFolderTarget.value.trim() ? activeFolderTarget.value.trim().split(/\r?\n/).pop() : "";
        loadFolders(value);
      });
    });
    document.getElementById("folderClose").onclick = () => document.getElementById("folderModal").classList.remove("open");
    document.getElementById("folderSelect").onclick = () => {
      if (activeFolderTarget) {
        if (activeFolderTarget.tagName === "TEXTAREA" && activeFolderTarget.value.trim()) {
          activeFolderTarget.value = activeFolderTarget.value.replace(/\s*$/, "") + "\n" + currentFolderPath;
        } else {
          activeFolderTarget.value = currentFolderPath;
        }
      }
      document.getElementById("folderModal").classList.remove("open");
    };
  </script>
</body>
</html>
"""


NAV = {
    "linkgen": "LinkGen Pro",
    "organizer": "Photo Organizer",
    "rename": "Rename Photo",
    "grid": "Image Grid Generator",
    "excel": "Excel Product Folder Automator",
    "settings": "Server Notes",
}


def page(active: str, content: str) -> str:
    return render_template_string(BASE_TEMPLATE, nav=NAV, active=active, content=content, server_root=str(SERVER_ROOT), browse_root=str(BROWSE_ROOT))


def result_table(result: Result) -> str:
    if not result.rows:
        return "<p class='hint'>No rows returned.</p>"
    keys: list[str] = []
    for row in result.rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    head = "".join(f"<th>{key}</th>" for key in keys)
    body = "".join("<tr>" + "".join(f"<td>{row.get(key, '')}</td>" for key in keys) + "</tr>" for row in result.rows[:500])
    note = "" if len(result.rows) <= 500 else f"<p class='hint'>Showing first 500 of {len(result.rows)} rows.</p>"
    return f"<h2>{result.title}</h2><p class='hint'>{result.summary}</p>{note}<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


@app.get("/")
def home() -> Response:
    return redirect(url_for("tool_page", tool="linkgen"))


@app.get("/api/folders")
def api_folders():
    try:
        raw_path = request.args.get("path", "").strip()
        current = resolve_server_path(raw_path) if raw_path else BROWSE_ROOT
        current = current.resolve()
        if not is_under_root(current):
            current = BROWSE_ROOT
        ensure_dir(current, "Folder")
        folders = []
        for child in sorted([p for p in current.iterdir() if p.is_dir()], key=number_sort_key):
            try:
                folders.append({"name": child.name, "path": str(child)})
            except OSError:
                continue
        parent = current.parent if current != BROWSE_ROOT and is_under_root(current.parent) else None
        return jsonify({"path": str(current), "parent": str(parent) if parent else "", "folders": folders})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/tool/<tool>", methods=["GET", "POST"])
def tool_page(tool: str) -> str:
    try:
        if tool == "linkgen":
            return linkgen_page()
        if tool == "organizer":
            return organizer_page()
        if tool == "rename":
            return rename_page()
        if tool == "grid":
            return grid_page()
        if tool == "excel":
            return excel_page()
        if tool == "settings":
            return settings_page()
    except Exception as exc:
        flash(str(exc))
        return page(tool, f"<div class='panel'><h1>Error</h1><p class='hint'>{exc}</p></div>")
    return page("settings", "<div class='panel'><h1>Not found</h1></div>")


def linkgen_page() -> str:
    result_html = ""
    urls_box = ""
    base_url = request.form.get("base_url", "https://primexeu.com/photos/VS/8/")
    folders = request.form.get("folders", "")
    include_subfolders = request.form.get("include_subfolders") == "on"
    check_urls = request.form.get("check_urls") == "on"
    if request.method == "POST":
        folder_paths = [resolve_server_path(line) for line in folders.splitlines() if line.strip()]
        result = generate_urls(base_url, folder_paths, include_subfolders, check_urls)
        result_html = result_table(result)
        urls_box = "\n".join(row["url"] for row in result.rows)
    content = f"""
    <div class="top"><div><h1>LinkGen Pro</h1><div class="hint">Generate website URLs from image/PDF files stored on the server.</div></div></div>
    <form method="post" class="panel">
      <div class="form-grid">
        <div class="field full"><label>Base URL</label><input name="base_url" value="{base_url}"></div>
        <div class="field full"><label>Server folders, one per line</label><div class="inline-input"><textarea id="linkgen-folders" name="folders" placeholder="{SERVER_ROOT}\\ProductFolder">{folders}</textarea><button type="button" class="browse-btn" data-browse-for="#linkgen-folders">Browse</button></div></div>
        <label class="check"><input type="checkbox" name="include_subfolders" {'checked' if include_subfolders else ''}> Use subfolders inside each parent folder</label>
        <label class="check"><input type="checkbox" name="check_urls" {'checked' if check_urls else ''}> Check URL status after generating</label>
      </div><p><button>Generate URLs</button></p>
    </form>
    {f'<div class="panel"><h2>Copy URLs</h2><div class="copybox">{urls_box}</div></div>' if urls_box else ''}
    <div class="panel">{result_html}</div>
    """
    return page("linkgen", content)


def organizer_page() -> str:
    result_html = ""
    source = request.form.get("source", "")
    destination = request.form.get("destination", "")
    if request.method == "POST":
        result_html = result_table(organize_photos(resolve_server_path(source), resolve_server_path(destination)))
    content = f"""
    <div class="top"><div><h1>Photo Organizer</h1><div class="hint">Copy images into destination subfolders using the numeric code before the first underscore.</div></div></div>
    <form method="post" class="panel">
      <div class="form-grid">
        <div class="field"><label>Source folder</label><div class="inline-input"><input id="organizer-source" name="source" value="{source}" placeholder="{SERVER_ROOT}\\source"><button type="button" class="browse-btn" data-browse-for="#organizer-source">Browse</button></div></div>
        <div class="field"><label>Destination folder</label><div class="inline-input"><input id="organizer-destination" name="destination" value="{destination}" placeholder="{SERVER_ROOT}\\organized"><button type="button" class="browse-btn" data-browse-for="#organizer-destination">Browse</button></div></div>
      </div><p><button>Organize Photos</button></p>
    </form>
    <div class="panel">{result_html}</div>
    """
    return page("organizer", content)


def rename_page() -> str:
    result_html = ""
    source = request.form.get("source", "")
    if request.method == "POST":
        result_html = result_table(rename_artikelbild(resolve_server_path(source)))
    content = f"""
    <div class="top"><div><h1>Rename Photo</h1><div class="hint">Copy files containing Artikelbild into Renamed_Photos using the first number as the filename.</div></div></div>
    <form method="post" class="panel">
      <div class="field"><label>Source folder</label><div class="inline-input"><input id="rename-source" name="source" value="{source}" placeholder="{SERVER_ROOT}\\photos"><button type="button" class="browse-btn" data-browse-for="#rename-source">Browse</button></div></div>
      <p><button>Rename Photos</button></p>
    </form>
    <div class="panel">{result_html}</div>
    """
    return page("rename", content)


def grid_page() -> str:
    result_html = ""
    parent = request.form.get("parent", "")
    variant = request.form.get("variant", "standard")
    export_format = request.form.get("format", "png")
    delete_original = request.form.get("delete_original") == "on"
    selected = request.form.getlist("quantities") or ["1", "3", "6", "12", "12_alt"]
    if request.method == "POST":
        result_html = result_table(generate_grids(resolve_server_path(parent), selected, export_format, variant, delete_original))
    qty_checks = "".join(
        f'<label class="check"><input type="checkbox" name="quantities" value="{q}" {"checked" if q in selected else ""}> {q}</label>'
        for q in ["1", "3", "6", "12", "12_alt"]
    )
    content = f"""
    <div class="top"><div><h1>Image Grid Generator</h1><div class="hint">Create grid images inside each product subfolder on the server.</div></div></div>
    <form method="post" class="panel">
      <div class="form-grid">
        <div class="field full"><label>Parent folder containing product subfolders</label><div class="inline-input"><input id="grid-parent" name="parent" value="{parent}" placeholder="{SERVER_ROOT}\\parent"><button type="button" class="browse-btn" data-browse-for="#grid-parent">Browse</button></div></div>
        <div class="field"><label>Generator</label><select name="variant">
          <option value="standard" {"selected" if variant=="standard" else ""}>4x4x4</option>
          <option value="fg" {"selected" if variant=="fg" else ""}>4x4x4 FG</option>
          <option value="big" {"selected" if variant=="big" else ""}>Big Bottle</option>
        </select></div>
        <div class="field"><label>Format</label><select name="format"><option value="png" {"selected" if export_format=="png" else ""}>PNG</option><option value="jpg" {"selected" if export_format=="jpg" else ""}>JPG</option></select></div>
        <div class="field full"><label>Quantities</label><div class="checks">{qty_checks}</div></div>
        <label class="check"><input type="checkbox" name="delete_original" {"checked" if delete_original else ""}> Delete original source image after successful generation</label>
      </div><p><button>Generate Grid Images</button></p>
    </form>
    <div class="panel">{result_html}</div>
    """
    return page("grid", content)


def excel_page() -> str:
    content = """
    <div class="top"><div><h1>Excel Product Folder Automator</h1><div class="hint">This one needs a second conversion step.</div></div></div>
    <div class="panel">
      <p>The desktop script supports Excel sheet selection, column mapping, local image paths, URL downloads, and embedded Excel images.</p>
      <p>The web version should be built as a separate server job so large Excel/image runs do not time out in the browser. I can convert this next with: upload/select Excel file, choose sheet/header row, choose folder-name and image columns, then run and show a job log.</p>
    </div>
    """
    return page("excel", content)


def settings_page() -> str:
    content = f"""
    <div class="top"><div><h1>Server Notes</h1><div class="hint">Use this app on the same server that can access the files.</div></div></div>
    <div class="panel">
      <p><strong>Current file root:</strong> {SERVER_ROOT}</p>
      <p>For hosting, set <code>VS_FILE_ROOT</code> to the server folder or UNC path. Windows services often cannot see mapped drives like <code>W:</code>; use a UNC path such as <code>\\\\server\\share\\folder</code> when hosting under IIS, Task Scheduler, or a service.</p>
      <p>Run locally for testing:</p>
      <div class="copybox">py -3 -m pip install flask pillow pandas openpyxl requests
py -3 web_dashboard.py</div>
    </div>
    """
    return page("settings", content)


@app.get("/files/<path:name>")
def serve_file(name: str):
    return send_from_directory(SERVER_ROOT, name)


if __name__ == "__main__":
    app.run(
        host=os.environ.get("VS_DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("VS_DASHBOARD_PORT", "8780")),
        debug=os.environ.get("VS_DASHBOARD_DEBUG", "0") == "1",
    )
