"""Replace a detected Riegel watermark with locally generated surrounding image content."""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import sys
import threading

import cv2
import numpy as np
from PIL import Image, ImageOps

from riegel_logo_detector import detect_logo

MODEL_NAME = "inpainting_lama_2025jan.onnx"
MODEL_SIZE = 256
_MODEL = None
_MODEL_LOCK = threading.RLock()


class _OnnxRuntimeModel:
    def __init__(self, session):
        self.session = session
        self.inputs = {}

    def setInput(self, data, name):
        self.inputs[name] = data

    def forward(self):
        return self.session.run(None, self.inputs)[0]


def model_path() -> Path:
    override = os.environ.get("RIEGEL_INPAINT_MODEL", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override))
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "VS-Tools" / "models" / MODEL_NAME)
    candidates.append(Path(__file__).resolve().parent / "models" / MODEL_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Local LaMa inpainting model is missing. See models/README.md.")


def model_available() -> bool:
    try:
        model_path()
        return True
    except RuntimeError:
        return False


def _get_model():
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            cv2.setNumThreads(4)
            try:
                import onnx
                import onnxruntime

                graph = onnx.load(str(model_path()))
                for input_value in graph.graph.input:
                    if input_value.name in {"image", "mask"}:
                        for dimension in input_value.type.tensor_type.shape.dim[2:]:
                            dimension.dim_value = MODEL_SIZE
                options = onnxruntime.SessionOptions()
                options.intra_op_num_threads = 4
                options.log_severity_level = 4
                session = onnxruntime.InferenceSession(
                    graph.SerializeToString(), sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
                _MODEL = _OnnxRuntimeModel(session)
            except ImportError:
                _MODEL = cv2.dnn.readNetFromONNX(str(model_path()))
        return _MODEL


def preload_model() -> None:
    if not model_available():
        return
    try:
        _get_model()
    except Exception as exc:
        print(f"Riegel inpainting model could not load: {exc}", file=sys.stderr, flush=True)


def _replace_region(rgb: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    image_height, image_width = rgb.shape[:2]
    x, y, width, height = box
    side = max(256, round(max(width, height) * 2.5))
    center_x, center_y = x + width // 2, y + height // 2
    left, top = center_x - side // 2, center_y - side // 2
    source_left, source_top = max(0, left), max(0, top)
    source_right, source_bottom = min(image_width, left + side), min(image_height, top + side)

    canvas = np.full((side, side, 3), 255, dtype=np.uint8)
    canvas[source_top - top:source_bottom - top, source_left - left:source_right - left] = (
        rgb[source_top:source_bottom, source_left:source_right]
    )
    mask = np.zeros((side, side), dtype=np.uint8)
    margin = max(4, round(min(width, height) * 0.07))
    mask[
        max(0, y - top - margin):min(side, y + height - top + margin),
        max(0, x - left - margin):min(side, x + width - left + margin),
    ] = 255

    image_blob = cv2.dnn.blobFromImage(
        cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR), 1 / 255, (MODEL_SIZE, MODEL_SIZE),
        (0, 0, 0), False, False,
    )
    mask_blob = (cv2.dnn.blobFromImage(mask, 1, (MODEL_SIZE, MODEL_SIZE), (0,), False, False) > 0).astype(np.float32)
    with _MODEL_LOCK:
        model = _get_model()
        model.setInput(image_blob, "image")
        model.setInput(mask_blob, "mask")
        prediction = model.forward()

    patch = np.transpose(prediction[0], (1, 2, 0)).clip(0, 255).astype(np.uint8)
    patch = cv2.resize(patch, (side, side), interpolation=cv2.INTER_CUBIC)
    patch = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
    alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 3)
    blended = (patch.astype(np.float32) * alpha[:, :, None] + canvas.astype(np.float32) * (1 - alpha[:, :, None])).clip(0, 255).astype(np.uint8)

    result = rgb.copy()
    result[source_top:source_bottom, source_left:source_right] = blended[
        source_top - top:source_bottom - top, source_left - left:source_right - left
    ]
    return result


def remove_detected_logo(path: Path) -> tuple[bytes, dict[str, object]]:
    detection = detect_logo(path)
    if not detection.get("match"):
        raise ValueError("Riegel logo was not found in this image.")
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    x, y, width, height = (int(value) for value in detection["bbox"])
    if width < 1 or height < 1 or x < 0 or y < 0 or x + width > image.width or y + height > image.height:
        raise ValueError("Detected logo coordinates are outside the image.")
    cleaned = _replace_region(np.asarray(image), (x, y, width, height))
    output = BytesIO()
    Image.fromarray(cleaned).save(output, format="PNG")
    return output.getvalue(), detection