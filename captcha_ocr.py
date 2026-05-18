"""Local OCR helper for security-code images.

The heavy OCR dependencies are imported lazily so the monitor can run in manual
mode without installing the optional OCR stack.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any


SUBMODULE_DIR = Path(__file__).parent / "third_party" / "OCR-for-Captcha"
MODEL_REPO_ID = "toandev/OCR-for-Captcha"
MODEL_FILENAME = "model.onnx"
IMAGE_SIZE = (32, 128)
VOCAB = r"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"

_OCR_MODEL: "CaptchaOCR | None" = None


def clean_prediction(prediction: str) -> str:
    """Keep the OCR output form-friendly while preserving case."""
    return re.sub(r"\s+", "", prediction).strip()


def _require_submodule() -> None:
    tokenizer_path = SUBMODULE_DIR / "utils" / "tokenizer_base.py"
    if not tokenizer_path.exists():
        raise RuntimeError(
            "OCR submodule is missing. Run: "
            "git submodule update --init --recursive third_party/OCR-for-Captcha"
        )


@dataclass
class CaptchaOCR:
    model_repo_id: str = MODEL_REPO_ID
    model_filename: str = MODEL_FILENAME

    def __post_init__(self) -> None:
        self._transform: Any | None = None
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._input_name: str | None = None

    def predict_bytes(self, image_bytes: bytes) -> str:
        image = self._load_image(image_bytes)
        return self.predict_image(image)

    def predict_image(self, image: Any) -> str:
        self._ensure_loaded()

        import torch

        tensor = self._transform(image.convert("RGB")).unsqueeze(0)
        ort_inputs = {self._input_name: self._to_numpy(tensor)}
        logits = self._session.run(None, ort_inputs)[0]
        probs = torch.tensor(logits).softmax(-1)
        predictions, _ = self._tokenizer.decode(probs)
        return clean_prediction(predictions[0])

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return

        _require_submodule()

        if str(SUBMODULE_DIR) not in sys.path:
            sys.path.insert(0, str(SUBMODULE_DIR))

        try:
            import onnx
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from torchvision import transforms as transforms
            from utils.tokenizer_base import Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "OCR dependencies are not installed. Run: "
                "pip install -r requirements-ocr.txt"
            ) from exc

        model_file = hf_hub_download(self.model_repo_id, self.model_filename)
        onnx_model = onnx.load(model_file)
        onnx.checker.check_model(onnx_model)

        transform = transforms.Compose(
            [
                transforms.Resize(IMAGE_SIZE, transforms.InterpolationMode.BICUBIC),
                transforms.ToTensor(),
                transforms.Normalize(0.5, 0.5),
            ]
        )
        session = ort.InferenceSession(model_file)

        self._transform = transform
        self._session = session
        self._tokenizer = Tokenizer(VOCAB)
        self._input_name = session.get_inputs()[0].name

    @staticmethod
    def _load_image(image_bytes: bytes) -> Any:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "Pillow is not installed. Run: pip install -r requirements-ocr.txt"
            ) from exc

        return Image.open(BytesIO(image_bytes))

    @staticmethod
    def _to_numpy(tensor: Any) -> Any:
        return (
            tensor.detach().cpu().numpy()
            if getattr(tensor, "requires_grad", False)
            else tensor.cpu().numpy()
        )


def predict_captcha_bytes(image_bytes: bytes) -> str:
    global _OCR_MODEL
    if _OCR_MODEL is None:
        _OCR_MODEL = CaptchaOCR()
    return _OCR_MODEL.predict_bytes(image_bytes)
