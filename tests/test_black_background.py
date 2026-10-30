from io import BytesIO
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Thread
import time
import unittest
import tempfile
import zipfile
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hetzner_url_dashboard as app
from black_background_scanner import scan_image, replace_black_background


class AuthenticatedHandler(app.Handler):
    def is_authenticated(self):
        return True

    def current_user(self):
        return {"username": "black-background-test"}

    def log_message(self, *_args):
        pass


def photo_bytes(background, center):
    image = Image.new("RGB", (200, 200), background)
    ImageDraw.Draw(image).ellipse((55, 35, 145, 165), fill=center)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class BlackBackgroundTests(unittest.TestCase):
    def test_scan_distinguishes_background_from_center_object(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            black = Path(directory) / "black.png"
            white = Path(directory) / "white.png"
            black.write_bytes(photo_bytes("black", "white"))
            white.write_bytes(photo_bytes("white", "black"))
            self.assertTrue(scan_image(black)["match"])
            self.assertFalse(scan_image(white)["match"])

    def test_conversion_whitens_outer_background_and_preserves_inner_black_detail(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "photo.png"
            image = Image.new("RGB", (200, 200), "black")
            draw = ImageDraw.Draw(image)
            draw.ellipse((45, 25, 155, 175), fill="white")
            draw.rectangle((85, 85, 115, 115), fill="black")
            image.save(path)
            original = path.read_bytes()
            data, detection = replace_black_background(path)
            self.assertTrue(detection["match"])
            with Image.open(BytesIO(data)) as cleaned:
                self.assertEqual(cleaned.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(cleaned.getpixel((100, 100)), (0, 0, 0))
                self.assertEqual(cleaned.size, image.size)
            self.assertEqual(path.read_bytes(), original)
    def test_conversion_removes_dark_antialias_fringe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "antialiased.png"
            image = Image.new("RGB", (800, 800), "black")
            ImageDraw.Draw(image).ellipse((160, 80, 640, 720), fill=(230, 180, 90))
            image = image.resize((200, 200), Image.Resampling.LANCZOS)
            image.save(path)
            data, _ = replace_black_background(path)
            original = np.asarray(image)
            converted = np.asarray(Image.open(BytesIO(data)))
            edge = (original[:, :, 0] > 15) & (original[:, :, 0] < 215)
            self.assertGreater(int(edge.sum()), 100)
            self.assertGreaterEqual(int(converted[:, :, 0][edge].min()), 235)
    def test_conversion_removes_wider_dark_contour(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dark-contour.png"
            image = Image.new("RGB", (800, 800), "black")
            draw = ImageDraw.Draw(image)
            draw.ellipse((145, 65, 655, 735), fill=(25, 20, 10))
            draw.ellipse((160, 80, 640, 720), fill=(230, 180, 90))
            image = image.resize((200, 200), Image.Resampling.LANCZOS)
            image.save(path)
            data, _ = replace_black_background(path)
            converted = np.asarray(Image.open(BytesIO(data)))
            dark_contour = (converted[:, :, 0] < 100) & (converted[:, :, 1] < 100)
            self.assertEqual(int(dark_contour.sum()), 0)
    def test_conversion_preserves_dark_bottle_against_black_background(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dark-bottle.png"
            image = Image.new("RGB", (240, 320), (0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((78, 40, 162, 282), radius=20, fill=(48, 48, 48))
            draw.rectangle((100, 12, 140, 55), fill=(48, 48, 48))
            draw.rectangle((82, 145, 158, 220), fill=(220, 210, 190))
            image.save(path)
            data, _ = replace_black_background(path)
            with Image.open(BytesIO(data)) as cleaned:
                self.assertEqual(cleaned.getpixel((0, 0)), (255, 255, 255))
                self.assertLess(max(cleaned.getpixel((120, 75))), 90)
                self.assertEqual(cleaned.getpixel((120, 175)), (220, 210, 190))
    def test_convert_all_zip_contains_upload_folder_and_url(self):
        class QuietFiles(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "black.png"
            source_bytes = photo_bytes("black", "white")
            path.write_bytes(source_bytes)
            files = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                lambda *args, **kwargs: QuietFiles(*args, directory=directory, **kwargs),
            )
            api = ThreadingHTTPServer(("127.0.0.1", 0), AuthenticatedHandler)
            threads = [Thread(target=server.serve_forever, daemon=True) for server in (files, api)]
            for thread in threads:
                thread.start()
            job_id = None
            try:
                file_url = f"http://127.0.0.1:{files.server_address[1]}/black.png"
                api_url = f"http://127.0.0.1:{api.server_address[1]}"
                manifest = [
                    {"source": "upload", "uploadIndex": 0},
                    {"source": "folder", "path": str(path)},
                    {"source": "url", "url": file_url},
                ]
                boundary = "black-convert-test-boundary"
                body = (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="manifest"\r\n\r\n'
                    f'{json.dumps(manifest)}\r\n'
                    f'--{boundary}\r\nContent-Disposition: form-data; name="upload_0"; filename="black.png"\r\n'
                    f'Content-Type: image/png\r\n\r\n'
                ).encode() + source_bytes + f'\r\n--{boundary}--\r\n'.encode()
                request = Request(
                    api_url + "/api/scan-black-background/convert-all", data=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    started = json.load(response)
                job_id = started["job_id"]
                for _ in range(100):
                    with urlopen(api_url + "/api/job?id=" + job_id, timeout=10) as response:
                        state = json.load(response)
                    if state["done"]:
                        break
                    time.sleep(0.1)
                self.assertTrue(state["done"])
                self.assertTrue(state["ok"], state["message"])
                self.assertEqual(state["created"], 3)
                with urlopen(api_url + "/api/scan-black-background/convert-all/download?id=" + job_id) as response:
                    archive_bytes = response.read()
                    self.assertIn("White_Background.zip", response.headers["Content-Disposition"])
                with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
                    names = archive.namelist()
                    self.assertEqual(len(names), 3)
                    self.assertEqual(len(set(names)), 3)
                    for name in names:
                        self.assertTrue(name.startswith("White_Background/"))
                        with Image.open(BytesIO(archive.read(name))) as converted:
                            self.assertEqual(converted.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(path.read_bytes(), source_bytes)
            finally:
                for server in (files, api):
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join(timeout=2)
                if job_id:
                    job = app.JOBS.pop(job_id, {})
                    output = job.get("output_path")
                    if output:
                        Path(output).unlink(missing_ok=True)
    def test_upload_job_reports_black_background(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), AuthenticatedHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        job_id = None
        try:
            root = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(root + "/black-background-scanner") as response:
                page = response.read().decode()
            self.assertIn("Black Background Scanner", page)
            self.assertIn('href="/black-background-scanner"', page)
            boundary = "black-background-test-boundary"
            parts = []
            for name, background, center in (
                ("black.png", "black", "white"),
                ("white.png", "white", "black"),
            ):
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                    f'Content-Type: image/png\r\n\r\n'.encode()
                    + photo_bytes(background, center) + b'\r\n'
                )
            body = b"".join(parts) + f"--{boundary}--\r\n".encode()
            request = Request(
                root + "/api/scan-black-background", data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                started = json.load(response)
            job_id = started["job_id"]
            for _ in range(50):
                with urlopen(root + "/api/job?id=" + job_id, timeout=10) as response:
                    result = json.load(response)
                if result["done"]:
                    break
                time.sleep(0.1)
            self.assertTrue(result["done"])
            self.assertTrue(result["ok"], result["message"])
            self.assertEqual(result["scanned"], 2)
            self.assertEqual(result["found"], 1)
            self.assertEqual([row["match"] for row in result["rows"]], [True, False])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            if job_id:
                app.JOBS.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()