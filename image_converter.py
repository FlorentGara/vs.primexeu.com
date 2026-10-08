from __future__ import annotations

import io
import ipaddress
import socket
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
OUTPUT_FORMATS = {
    "png": ("PNG", "image/png"),
    "jpg": ("JPEG", "image/jpeg"),
    "webp": ("WEBP", "image/webp"),
    "gif": ("GIF", "image/gif"),
    "bmp": ("BMP", "image/bmp"),
    "tiff": ("TIFF", "image/tiff"),
    "avif": ("AVIF", "image/avif"),
    "ico": ("ICO", "image/x-icon"),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Shkruaj nje link publik http ose https te fotos.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as exc:
        raise ValueError("Linku nuk mund te hapet.") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Linku duhet te jete publik.")


def download_image(url: str) -> bytes:
    opener = build_opener(ProxyHandler({}), NoRedirect())
    for _ in range(4):
        validate_public_url(url)
        request = Request(url, headers={"User-Agent": "VS-Tools-Image-Converter/1.0"})
        try:
            response = opener.open(request, timeout=20)
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                exc.close()
                if not location:
                    raise ValueError("Linku nuk ka adrese te vlefshme ridrejtimi.")
                url = urljoin(url, location)
                continue
            raise ValueError("Fotoja nuk mund te shkarkohet nga linku.") from exc
        with response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_IMAGE_BYTES:
                raise ValueError("Fotoja eshte me e madhe se 25 MB.")
            data = response.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Fotoja eshte me e madhe se 25 MB.")
        return data
    raise ValueError("Linku ka shume ridrejtime.")


def convert_image(data: bytes, output_format: str, width: int | None = None, height: int | None = None) -> tuple[bytes, str]:
    output_format = output_format.lower()
    if output_format not in OUTPUT_FORMATS:
        raise ValueError("Zgjidh PNG, JPG, WEBP, GIF, BMP, TIFF, AVIF ose ICO.")
    if (width is None) != (height is None):
        raise ValueError("Shkruaj gjeresine dhe lartesine, ose leri te dyja bosh.")
    if width is not None:
        if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
            raise ValueError("Permasat duhet te jene numra pozitive deri ne 50 milione piksela gjithsej.")
        if output_format == "ico" and (width > 256 or height > 256):
            raise ValueError("Formati ICO pranon permasa deri ne 256 x 256 piksela.")
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Fotoja duhet te jete deri ne 25 MB.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Fotoja eshte shume e madhe per konvertim.")
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            image.load()
            if width is not None:
                image = image.resize((width, height), Image.Resampling.LANCZOS)
            result = io.BytesIO()
            name, mime = OUTPUT_FORMATS[output_format]
            if output_format in {"jpg", "bmp"}:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif output_format == "ico":
                image = image.convert("RGBA")
                if max(image.size) > 256:
                    image.thumbnail((256, 256), Image.Resampling.LANCZOS)
            elif output_format == "gif":
                image = image.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE)
            elif image.mode not in {"RGB", "RGBA", "L", "LA"}:
                image = image.convert("RGBA")
            options = {"quality": 92, "optimize": True} if output_format == "jpg" else {}
            if output_format == "ico" and width is not None:
                options = {"sizes": [image.size]}
            elif output_format == "avif":
                options = {"quality": 85}
            elif output_format == "webp":
                options = {"quality": 90, "method": 4}
            elif output_format == "png":
                options = {"optimize": True}
            elif output_format == "tiff":
                options = {"compression": "tiff_deflate"}
            image.save(result, format=name, **options)
            return result.getvalue(), mime
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Skedari ose linku nuk permban foto te vlefshme.") from exc
