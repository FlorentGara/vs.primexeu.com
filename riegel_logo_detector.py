"""Locate the supplied Riegel bioweine logo within product photos."""

from __future__ import annotations

import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageOps
except ImportError:
    cv2 = None
    np = None
    Image = None
    ImageDraw = None
    ImageOps = None

REFERENCE_PATH = Path(__file__).resolve().parent / "static" / "riegel-logo-reference.png"
OVERLAP_REFERENCE_PATH = Path(__file__).resolve().parent / "static" / "riegel-logo-label-overlap.png"
PALE_REFERENCE_PATHS = tuple(Path(__file__).resolve().parent / "static" / name for name in (
    "riegel-logo-pale-gold.png", "riegel-logo-pale-rose.png", "riegel-logo-pale-bottle.png",
))
EXAMPLE_REFERENCE_PATHS = tuple(sorted((Path(__file__).resolve().parent / 'static' / 'riegel-logo-examples').glob('*.png')))
SCALES = (0.4, 0.5, 0.6, 0.75, 0.9, 1.0, 1.15, 1.35, 1.6, 2.0)
MAX_SCAN_SIDE = 1200


@lru_cache(maxsize=32)
def reference(path: Path = REFERENCE_PATH):
    if Image is None or cv2 is None or np is None:
        raise RuntimeError("Logo localization requires Pillow, NumPy, and OpenCV.")
    with Image.open(path) as source:
        rgb = np.asarray(source.convert("RGB"))
    if path == REFERENCE_PATH:
        foreground = np.any(rgb < 230, axis=2)
        ys, xs = np.where(foreground)
        if not len(xs):
            raise ValueError("Riegel logo reference is blank.")
        left, top = max(0, int(xs.min()) - 3), max(0, int(ys.min()) - 3)
        right, bottom = min(rgb.shape[1], int(xs.max()) + 4), min(rgb.shape[0], int(ys.max()) + 4)
        rgb = rgb[top:bottom, left:right].copy()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    sift = cv2.SIFT_create()
    variants = []
    for name, variant in (("dark-on-light", gray), ("light-on-dark", 255 - gray)):
        points, descriptors = sift.detectAndCompute(variant, None)
        if descriptors is not None:
            variants.append((name, points, descriptors))
    return rgb, gray, variants


def feature_location(candidate_gray):
    sift = cv2.SIFT_create()
    points, descriptors = sift.detectAndCompute(candidate_gray, None)
    if descriptors is None or len(points) < 8:
        return None
    matcher = cv2.BFMatcher()
    best = None
    for reference_path in (REFERENCE_PATH, OVERLAP_REFERENCE_PATH, *PALE_REFERENCE_PATHS, *EXAMPLE_REFERENCE_PATHS):
        _, ref_gray, variants = reference(reference_path)
        for variant_name, ref_points, ref_descriptors in variants:
            pairs = matcher.knnMatch(ref_descriptors, descriptors, k=2)
            matches = [first for first, second in pairs if first.distance < 0.72 * second.distance]
            if len(matches) < 8:
                continue
            source = np.float32([ref_points[match.queryIdx].pt for match in matches]).reshape(-1, 1, 2)
            target = np.float32([points[match.trainIdx].pt for match in matches]).reshape(-1, 1, 2)
            transform, inlier_mask = cv2.findHomography(source, target, cv2.RANSAC, 4.0)
            if transform is None or inlier_mask is None:
                continue
            inliers = int(inlier_mask.sum())
            if inliers < 7 or inliers / len(matches) < 0.55:
                continue
            height, width = ref_gray.shape
            corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]]).reshape(-1, 1, 2)
            polygon = cv2.perspectiveTransform(corners, transform).reshape(-1, 2)
            if not np.isfinite(polygon).all() or not cv2.isContourConvex(polygon.astype(np.float32)):
                continue
            if cv2.contourArea(polygon.astype(np.float32)) < 180:
                continue
            x0, y0 = polygon.min(axis=0)
            x1, y1 = polygon.max(axis=0)
            image_height, image_width = candidate_gray.shape
            if x0 < -5 or y0 < -5 or x1 > image_width + 5 or y1 > image_height + 5:
                continue
            if x1 - x0 < 18 or y1 - y0 < 12 or (x1 - x0) / (y1 - y0) > 4:
                continue
            result = (
                (float(x0), float(y0), float(x1), float(y1)),
                min(0.99, 0.72 + inliers * 0.01),
                f"feature ({variant_name})",
                reference_path.name,
            )
            if best is None or inliers > best[0]:
                best = (inliers, result)
    return best[1] if best else None


def template_location(candidate_rgb, candidate_gray):
    ref_rgb, ref_gray, _ = reference()
    image_height, image_width = candidate_gray.shape
    best = (0.0, None)
    for scale in SCALES:
        size = (max(8, round(ref_gray.shape[1] * scale)), max(8, round(ref_gray.shape[0] * scale)))
        if size[0] > image_width or size[1] > image_height:
            continue
        method = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        template_gray = cv2.resize(ref_gray, size, interpolation=method)
        result = cv2.matchTemplate(candidate_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, gray_score, _, (x, y) = cv2.minMaxLoc(result)
        if gray_score <= best[0]:
            continue
        template_rgb = cv2.resize(ref_rgb, size, interpolation=method)
        patch = candidate_rgb[y:y + size[1], x:x + size[0]]
        color_score = float(cv2.matchTemplate(patch, template_rgb, cv2.TM_CCOEFF_NORMED)[0, 0])
        combined = 0.7 * gray_score + 0.3 * max(0.0, color_score)
        if combined > best[0]:
            best = (combined, (x, y, x + size[0], y + size[1]))
    score, box = best
    if box is not None and score >= 0.55:
        return tuple(float(value) for value in box), score, "template", REFERENCE_PATH.name
    return None, score, "template", REFERENCE_PATH.name


def edge_location(candidate_gray):
    # Match the lettering outline rather than bottle colour or brightness.
    # The supplied watermark sits above the main product label.
    _, ref_gray, _ = reference()
    reference_edges = cv2.Canny(ref_gray, 30, 100)
    candidate_edges = cv2.Canny(candidate_gray, 30, 100)
    image_height, image_width = candidate_gray.shape
    best = (0.0, None)
    for scale in (0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0):
        width = round(ref_gray.shape[1] * scale)
        height = round(ref_gray.shape[0] * scale)
        if width > image_width or height > image_height or width < image_width * 0.34:
            continue
        template = cv2.resize(reference_edges, (width, height))
        result_width = image_width - width + 1
        result_height = image_height - height + 1
        left = max(0, round(image_width * 0.28 - width / 2))
        right = min(result_width, round(image_width * 0.72 - width / 2) + 1)
        top = max(0, round(image_height * 0.18))
        bottom = min(result_height, round(image_height * 0.44) + 1)
        if left >= right or top >= bottom:
            continue
        region = candidate_edges[top:bottom + height - 1, left:right + width - 1]
        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (local_x, local_y) = cv2.minMaxLoc(result)
        if score > best[0]:
            x, y = left + local_x, top + local_y
            best = (score, (x, y, x + width, y + height))
    score, box = best
    if box is not None and score >= 0.22:
        return tuple(float(value) for value in box), score, 'edge template', REFERENCE_PATH.name
    return None


def example_location(candidate_gray):
    image_height, image_width = candidate_gray.shape
    best = (0.0, None, None)
    for reference_path in EXAMPLE_REFERENCE_PATHS:
        _, ref_gray, _ = reference(reference_path)
        for scale in (0.75, 1.0, 1.35, 1.8):
            width = round(ref_gray.shape[1] * scale)
            height = round(ref_gray.shape[0] * scale)
            if width > image_width or height > image_height:
                continue
            template = cv2.resize(ref_gray, (width, height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
            result_width = image_width - width + 1
            result_height = image_height - height + 1
            left = max(0, round(image_width * 0.28 - width / 2))
            right = min(result_width, round(image_width * 0.72 - width / 2) + 1)
            top = max(0, round(image_height * 0.18))
            bottom = min(result_height, round(image_height * 0.55) + 1)
            if left >= right or top >= bottom:
                continue
            region = candidate_gray[top:bottom + height - 1, left:right + width - 1]
            result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (local_x, local_y) = cv2.minMaxLoc(result)
            if score > best[0]:
                x, y = left + local_x, top + local_y
                best = (score, (x, y, x + width, y + height), reference_path.name)
    score, box, reference_name = best
    if box is not None and score >= 0.9:
        return tuple(float(value) for value in box), score, 'example template', reference_name
    return None


def annotated_preview(image, box):
    thumbnail = image.copy()
    thumbnail.thumbnail((420, 420), Image.Resampling.LANCZOS)
    factor_x = thumbnail.width / image.width
    factor_y = thumbnail.height / image.height
    x, y, width, height = box
    rectangle = (
        round(x * factor_x), round(y * factor_y),
        round((x + width) * factor_x), round((y + height) * factor_y),
    )
    draw = ImageDraw.Draw(thumbnail)
    line_width = max(2, round(min(thumbnail.size) / 130))
    draw.rectangle(rectangle, outline="#e11d48", width=line_width)
    output = BytesIO()
    thumbnail.save(output, format="JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def detect_logo(path: Path) -> dict[str, object]:
    if Image is None or cv2 is None or np is None:
        return {"checked": False, "match": False, "message": "Logo localization requires Pillow, NumPy, and OpenCV."}
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        original_width, original_height = image.size
        factor = min(1.0, MAX_SCAN_SIDE / max(image.size))
        candidate = np.asarray(image)
        if factor < 1:
            candidate = cv2.resize(candidate, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_RGB2GRAY)
        found = feature_location(candidate_gray)
        if found is None:
            found = example_location(candidate_gray)
        if found is None:
            found = edge_location(candidate_gray)
        if found is None:
            box, score, method, reference_name = template_location(candidate, candidate_gray)
        else:
            box, score, method, reference_name = found
        if box is None:
            return {
                "checked": True, "match": False, "score": round(float(score), 3),
                "reference": REFERENCE_PATH.name,
                "message": f"No match to the supplied Riegel logo. Best visual score {score:.3f}.",
            }
        x0, y0, x1, y1 = box
        x = max(0, round(x0 / factor))
        y = max(0, round(y0 / factor))
        right = min(original_width, round(x1 / factor))
        bottom = min(original_height, round(y1 / factor))
        pixel_box = [x, y, max(1, right - x), max(1, bottom - y)]
        center_x = (x + pixel_box[2] / 2) / original_width
        center_y = (y + pixel_box[3] / 2) / original_height
        horizontal = "left" if center_x < 1 / 3 else ("right" if center_x > 2 / 3 else "center")
        vertical = "top" if center_y < 1 / 3 else ("bottom" if center_y > 2 / 3 else "middle")
        position = f"{vertical} {horizontal} (x={x}, y={y}, {pixel_box[2]}x{pixel_box[3]} px)"
        return {
            "checked": True, "match": True, "score": round(float(score), 3),
            "reference": reference_name, "method": method,
            "bbox": pixel_box, "image_width": original_width, "image_height": original_height,
            "position": position, "preview": annotated_preview(image, pixel_box),
            "message": f"Supplied Riegel logo found at {position}.",
        }
    except Exception as exc:
        return {"checked": False, "match": False, "message": f"Could not analyze image: {exc}"}
