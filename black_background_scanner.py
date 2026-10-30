"""Find photos whose outer background is predominantly black."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image, ImageOps


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".pjg"}


def local_image_files(folder_text: str, recursive: bool) -> list[Path]:
    folder = Path(folder_text.strip().strip('"'))
    if not folder.is_dir():
        raise ValueError("Folder does not exist or is not a folder.")
    paths = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        (path for path in paths if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda path: str(path).lower(),
    )


def download_image(url: str) -> Path:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Only http/https image URLs are supported.")
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".jpg"
    request = Request(url, headers={"User-Agent": "VS-Tools-Black-Background-Scan/1.0"})
    with urlopen(request, timeout=20) as response:
        data = response.read(15 * 1024 * 1024 + 1)
    if len(data) > 15 * 1024 * 1024:
        raise ValueError("Image is larger than 15 MB.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
        temporary.write(data)
        return Path(temporary.name)


def scan_image(path: Path) -> dict[str, object]:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
    image.thumbnail((256, 256), Image.Resampling.LANCZOS)
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    background.alpha_composite(image)
    rgb = np.asarray(background.convert("RGB"))
    height, width = rgb.shape[:2]
    dark = np.max(rgb, axis=2) <= 55
    border = max(1, round(min(width, height) * 0.1))
    edge_pixels = np.concatenate((
        dark[:border, :].ravel(), dark[-border:, :].ravel(),
        dark[border:-border, :border].ravel(),
        dark[border:-border, -border:].ravel(),
    ))
    edge_percent = float(np.mean(edge_pixels)) if edge_pixels.size else 0.0
    corner = max(1, round(min(width, height) * 0.12))
    corners = (
        dark[:corner, :corner], dark[:corner, -corner:],
        dark[-corner:, :corner], dark[-corner:, -corner:],
    )
    dark_corners = sum(float(np.mean(part)) >= 0.7 for part in corners)
    match = edge_percent >= 0.8 and dark_corners >= 3
    result: dict[str, object] = {
        "match": match,
        "dark_percent": round(edge_percent * 100, 1),
        "status": "black background" if match else "other background",
        "message": f"{edge_percent:.0%} of border pixels are dark; {dark_corners}/4 corners are dark.",
    }
    if match:
        preview = background.convert("RGB")
        preview.thumbnail((150, 150), Image.Resampling.LANCZOS)
        output = BytesIO()
        preview.save(output, format="JPEG", quality=70)
        result["preview"] = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    return result



def replace_black_background(path: Path) -> tuple[bytes, dict[str, object]]:
    """Return a PNG copy with border-connected dark background replaced by white."""
    import cv2

    detection = scan_image(path)
    if not detection["match"]:
        raise ValueError("This photo does not have a detected black background.")
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
    canvas = Image.new("RGBA", image.size, (255, 255, 255, 255))
    canvas.alpha_composite(image)
    rgb = np.asarray(canvas.convert("RGB"))
    height, width = rgb.shape[:2]
    scale = min(1.0, 1400 / max(height, width))
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    small_height, small_width = small.shape[:2]
    brightness = np.max(small, axis=2)
    bright = brightness >= 125
    bright_count = int(bright.sum())
    foreground = None
    if 0.002 * bright.size <= bright_count <= 0.7 * bright.size:
        ys, xs = np.where(bright)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        pad_x = max(round(small_width * 0.08), round((x1 - x0) * 0.65))
        pad_y = max(round(small_height * 0.08), round((y1 - y0) * 1.2))
        x0, x1 = max(0, x0 - pad_x), min(small_width, x1 + pad_x)
        y0, y1 = max(0, y0 - pad_y), min(small_height, y1 + pad_y)
        mask = np.full((small_height, small_width), cv2.GC_PR_BGD, dtype=np.uint8)
        mask[y0:y1, x0:x1] = cv2.GC_PR_FGD
        edge = max(1, round(min(small_height, small_width) * 0.025))
        mask[:edge, :] = cv2.GC_BGD
        mask[-edge:, :] = cv2.GC_BGD
        mask[:, :edge] = cv2.GC_BGD
        mask[:, -edge:] = cv2.GC_BGD
        seeds = bright & (mask != cv2.GC_BGD)
        mask[seeds] = cv2.GC_FGD
        if seeds.any() and (mask == cv2.GC_BGD).any():
            try:
                cv2.grabCut(
                    cv2.cvtColor(small, cv2.COLOR_RGB2BGR), mask, None,
                    np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                    3, cv2.GC_INIT_WITH_MASK,
                )
                candidate = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
                _, components = cv2.connectedComponents(candidate, connectivity=8)
                keep = np.unique(components[seeds])
                keep = keep[keep != 0]
                candidate = np.isin(components, keep).astype(np.uint8)
                # Keep dark labels and other details enclosed by the product.
                enclosed = cv2.bitwise_not(candidate * 255)
                flood = enclosed.copy()
                cv2.floodFill(flood, np.zeros((small_height + 2, small_width + 2), np.uint8), (0, 0), 0)
                candidate |= (flood > 0).astype(np.uint8)
                share = float(candidate.mean())
                if 0.01 <= share <= 0.95:
                    foreground = candidate
            except cv2.error:
                pass
    if foreground is None:
        dark = (brightness <= 80).astype(np.uint8)
        _, labels = cv2.connectedComponents(dark, connectivity=4)
        border_labels = np.unique(np.concatenate((
            labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
        )))
        border_labels = border_labels[border_labels != 0]
        background_mask = np.isin(labels, border_labels).astype(np.float32)
    else:
        background_mask = 1.0 - foreground.astype(np.float32)
    if scale < 1:
        background_mask = cv2.resize(background_mask, (width, height), interpolation=cv2.INTER_LINEAR)
    alpha = cv2.GaussianBlur(background_mask, (0, 0), 0.8).clip(0, 1)
    corner = max(1, round(min(height, width) * 0.05))
    corners = np.concatenate((
        rgb[:corner, :corner].reshape(-1, 3),
        rgb[:corner, -corner:].reshape(-1, 3),
        rgb[-corner:, :corner].reshape(-1, 3),
        rgb[-corner:, -corner:].reshape(-1, 3),
    ))
    dark_corners = corners[np.max(corners, axis=1) <= 100]
    background_color = np.median(dark_corners, axis=0).astype(np.float32) if len(dark_corners) else np.zeros(3, np.float32)

    # Estimate how much of each edge pixel belongs to the original black backdrop.
    # The source edge is already composited over black, so its colour must not be
    # multiplied by foreground alpha a second time.
    local_foreground = cv2.dilate(rgb, np.ones((17, 17), np.uint8))
    numerator = np.zeros((height, width), np.float32)
    denominator = np.zeros((height, width), np.float32)
    for channel in range(3):
        observed = rgb[:, :, channel].astype(np.float32) - background_color[channel]
        nearby = local_foreground[:, :, channel].astype(np.float32) - background_color[channel]
        numerator += observed * nearby
        denominator += nearby * nearby
    hard_background = (background_mask >= 0.5).astype(np.uint8)
    kernel = np.ones((7, 7), np.uint8)
    near_background = cv2.dilate(hard_background, kernel) > 0
    near_foreground = cv2.dilate(1 - hard_background, kernel) > 0
    wide_kernel = np.ones((17, 17), np.uint8)
    dark_fringe = np.max(rgb, axis=2) <= 0.55 * np.max(local_foreground, axis=2)
    wide_band = (
        cv2.dilate(hard_background, wide_kernel) > 0
    ) & (
        cv2.dilate(1 - hard_background, wide_kernel) > 0
    )
    edge_band = ((near_background & near_foreground) | (dark_fringe & wide_band)) & (denominator > 400)
    estimated_background = 1 - np.clip(numerator / np.maximum(denominator, 1), 0, 1)
    alpha[edge_band] = estimated_background[edge_band]
    cleaned = rgb.astype(np.float32)
    for channel in range(3):
        cleaned[:, :, channel] += alpha * (255 - background_color[channel])
    cleaned = np.clip(cleaned, 0, 255).astype(np.uint8)
    output = BytesIO()
    Image.fromarray(cleaned).save(output, format="PNG")
    return output.getvalue(), detection

PAGE = r"""
<h1>Black Background Scanner</h1>
<p class="hint">Finds photos with mostly black borders and at least 3 dark corners. Convert All to White creates PNG copies with white backgrounds and downloads one ZIP. Original photos stay unchanged.</p>
<section class="panel">
  <div class="grid">
    <div class="field full"><label for="blackFiles">Upload photos</label><input id="blackFiles" type="file" accept=".jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff" multiple><span class="hint">Up to 20 photos, 15 MB each.</span></div>
    <div class="field full"><label for="blackUrls">Image URLs</label><textarea id="blackUrls" placeholder="One URL per line"></textarea></div>
    <div class="field full"><label for="blackFolder">Folder on server</label><input id="blackFolder" placeholder="Enter folder path"></div>
    <div class="field full"><label class="check"><input type="checkbox" id="blackRecursive" checked> Include subfolders</label></div>
  </div>
  <div class="actions"><button id="blackScanBtn" type="button">Scan photos</button><button id="blackConvertAllBtn" class="mutedbtn" type="button" disabled>Convert All to White &amp; Download ZIP</button><button id="blackCopyBtn" class="mutedbtn" type="button">Copy black background paths / URLs</button><button id="blackExportBtn" class="mutedbtn" type="button">Export CSV</button></div>
  <div class="progress" id="blackProgress"><div class="track"><div class="bar" id="blackProgressBar"></div></div><div class="label" id="blackProgressLabel">Waiting...</div></div>
  <div class="status" id="status"></div>
</section>
<section class="panel"><div class="cards">
  <div class="card"><div class="n" id="blackScanned">0</div><div class="t">images scanned</div></div>
  <div class="card"><div class="n" id="blackFound">0</div><div class="t">black background</div></div>
  <div class="card"><div class="n" id="blackIssues">0</div><div class="t">errors</div></div>
</div></section>
<section class="panel"><h2>Results</h2><div id="blackResults" class="hint">No scan results yet.</div></section>
<script>
(() => {
  let rows = [];
  let uploadedFiles = [];
  let scanReady = false;
  let batchRunning = false;
  const byId = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  const message = value => { const box=byId("status"); box.textContent=value; box.style.display="block"; };
  function render() {
    const hits=rows.filter(row=>row.match===true);
    byId("blackConvertAllBtn").disabled=!scanReady || batchRunning || hits.length===0;
    byId("blackScanned").textContent=rows.length;
    byId("blackFound").textContent=hits.length;
    byId("blackIssues").textContent=rows.filter(row=>row.status==="error").length;
    const shown=rows.slice(0,1200);
    if (!shown.length) { byId("blackResults").textContent="No scan results yet."; return; }
    const body=shown.map(row=>{
      const preview=row.preview?'<img src="'+escapeHtml(row.preview)+'" alt="Preview" style="max-width:120px;max-height:120px;object-fit:contain">':"";
      const link=row.url?'<a href="'+escapeHtml(row.url)+'" target="_blank" rel="noopener noreferrer">Open image</a>':"";
      return '<tr><td>'+escapeHtml(row.file)+'</td><td>'+escapeHtml(row.status)+'</td><td>'+escapeHtml(row.dark_percent ?? "-")+'%</td><td>'+preview+'</td><td>'+escapeHtml(row.path || "")+'</td><td>'+link+'</td><td>'+escapeHtml(row.message || "")+'</td></tr>';
    }).join("");
    const note=rows.length>shown.length?'<p class="hint">Showing the first 1200 of '+rows.length+'.</p>':"";
    byId("blackResults").innerHTML=note+'<div style="overflow:auto"><table><thead><tr><th>Image</th><th>Result</th><th>Dark border</th><th>Preview</th><th>Path</th><th>URL</th><th>Details</th></tr></thead><tbody>'+body+'</tbody></table></div>';
  }
  function progress(percent,label,active) {
    const wrap=byId("blackProgress");
    wrap.style.display="block"; wrap.classList.toggle("active",active);
    byId("blackProgressBar").style.width=Math.max(0,Math.min(100,percent))+"%";
    byId("blackProgressLabel").textContent=label;
  }
  byId("blackScanBtn").addEventListener("click",async()=>{
    const files=[...byId("blackFiles").files], urls=byId("blackUrls").value, folder=byId("blackFolder").value;
    if (!files.length && !urls.trim() && !folder.trim()) { message("Choose photos, enter URLs, or enter a folder path."); return; }
    if (files.length>20 || files.some(file=>file.size>15*1024*1024) || files.reduce((n,file)=>n+file.size,0)>80*1024*1024) { message("Choose up to 20 photos, 15 MB each and 80 MB total."); return; }
    const form=new FormData();
    files.forEach(file=>form.append("files",file));
    form.append("urls",urls); form.append("folder",folder); form.append("recursive",byId("blackRecursive").checked?"1":"0");
    byId("blackScanBtn").disabled=true; uploadedFiles=files; scanReady=false; rows=[]; render(); progress(3,"Starting scan...",true);
    try {
      const response=await fetch("/api/scan-black-background",{method:"POST",body:form});
      const started=await response.json();
      if (!response.ok) throw new Error(started.error || "Scan failed.");
      while (true) {
        const res=await fetch("/api/job?id="+encodeURIComponent(started.job_id),{cache:"no-store"});
        const data=await res.json();
        if (!res.ok) throw new Error(data.error || "Scan failed.");
        rows=data.rows || []; render(); progress(data.percent || 5,data.message || "Scanning photos...",!data.done);
        if (data.done) { if (!data.ok) throw new Error(data.message || "Scan failed."); scanReady=true; render(); message("Scanned "+rows.length+" photos; "+rows.filter(row=>row.match).length+" have a black background."); break; }
        await new Promise(resolve=>setTimeout(resolve,800));
      }
    } catch(error) { message(error.message); progress(100,"Scan stopped.",false); }
    finally { byId("blackScanBtn").disabled=false; }
  });
  byId("blackConvertAllBtn").addEventListener("click",async()=>{
    if (!scanReady || batchRunning) return;
    const hits=rows.filter(row=>row.match===true);
    if (!hits.length) { message("No black background photos to convert."); return; }
    const form=new FormData();
    form.append("manifest",JSON.stringify(hits.map(row=>({source:row.source,path:row.path,url:row.url,uploadIndex:row.uploadIndex}))));
    const appended=new Set();
    for (const row of hits) {
      if (row.source!=="upload") continue;
      const index=Number(row.uploadIndex);
      const file=uploadedFiles[index];
      if (!file) { message("An uploaded photo is no longer available. Scan again."); return; }
      if (!appended.has(index)) { form.append("upload_"+index,file); appended.add(index); }
    }
    batchRunning=true; render(); progress(3,"Starting conversion...",true);
    try {
      const response=await fetch("/api/scan-black-background/convert-all",{method:"POST",body:form});
      const started=await response.json();
      if (!response.ok) throw new Error(started.error || "Batch conversion failed.");
      while (true) {
        const res=await fetch("/api/job?id="+encodeURIComponent(started.job_id),{cache:"no-store"});
        const data=await res.json();
        if (!res.ok) throw new Error(data.error || "Batch conversion failed.");
        progress(data.percent || 5,data.message || "Converting photos...",!data.done);
        if (data.done) {
          if (!data.ok) throw new Error(data.message || "Batch conversion failed.");
          const link=document.createElement("a");
          link.href="/api/scan-black-background/convert-all/download?id="+encodeURIComponent(started.job_id);
          link.download="White_Background.zip";
          document.body.appendChild(link); link.click(); link.remove();
          message("Converted "+(data.created || 0)+" photo(s). ZIP download started. Errors: "+(data.issues || 0)+".");
          break;
        }
        await new Promise(resolve=>setTimeout(resolve,1200));
      }
    } catch(error) { message(error.message); progress(100,"Conversion stopped.",false); }
    finally { batchRunning=false; render(); }
  });  byId("blackCopyBtn").addEventListener("click",async()=>{
    const paths=rows.filter(row=>row.match).map(row=>row.url || row.path).filter(Boolean);
    if (!paths.length) { message("No black background photos to copy."); return; }
    try { await navigator.clipboard.writeText(paths.join("\n")); message("Copied "+paths.length+" paths/URLs."); }
    catch(error) { message("Browser blocked copying to clipboard."); }
  });
  byId("blackExportBtn").addEventListener("click",()=>{
    const header=["source","file","status","dark_percent","path","url","message"];
    const csv=[header.join(","),...rows.map(row=>header.map(key=>'"'+String(row[key] ?? "").replace(/"/g,'""')+'"').join(","))].join("\r\n");
    const link=document.createElement("a"); link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
    link.download="black-background-results.csv"; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  });
})();
</script>
"""