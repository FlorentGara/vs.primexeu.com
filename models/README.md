# Local Riegel inpainting model

VS Tools uses OpenCV Zoo's LaMa ONNX model to rebuild the area behind a detected Riegel watermark. Processing runs locally; no paid image API is used.

- Source: https://github.com/opencv/opencv_zoo/tree/main/models/inpainting_lama
- Model: `inpainting_lama_2025jan.onnx` (92,591,623 bytes)
- SHA-256: `7df918ac3921d3daf0aae1d219776cf0dc4e4935f035af81841b40adcf74fdf2`
- License: Apache 2.0; see `LICENSE`.

The model file is ignored by Git because it is 93 MB. Place it in this directory, set `RIEGEL_INPAINT_MODEL` to its path, or put it at `%LOCALAPPDATA%\VS-Tools\models\inpainting_lama_2025jan.onnx` on Windows. VS Tools prefers the local cache to avoid loading the model from a network share.

Official download: https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/inpainting_lama/inpainting_lama_2025jan.onnx

The first model load may take about two minutes on this CPU. Later images take only a few seconds. The model synthesizes plausible visual content; text that was hidden under a watermark cannot be recovered exactly.