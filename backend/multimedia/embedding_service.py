from functools import lru_cache
from pathlib import Path

import torch
import cv2
import numpy as np
import open_clip
from PIL import Image


MODEL_NAME = "ViT-B-32-quickgelu"
PRETRAINED = "openai"


@lru_cache(maxsize=1)
def get_clip():
    cache_dir = Path.home() / ".cache" / "eyesight" / "models" / "clip"
    cache_dir.mkdir(parents=True, exist_ok=True)

    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL_NAME,
        pretrained=PRETRAINED,
        device="cpu",
        cache_dir=str(cache_dir),
    )
    model.eval()

    tokenizer = open_clip.get_tokenizer(MODEL_NAME)
    return model, preprocess, tokenizer


def normalize_embedding(features):
    vector = features.detach().cpu().numpy().astype(np.float32).reshape(-1)

    if vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError("Embedding must contain finite numbers.")

    length = float(np.linalg.norm(vector))
    if length <= 0:
        raise ValueError("Embedding must have a positive length.")

    return vector / length


def embed_image(frame):
    if (
        not isinstance(frame, np.ndarray)
        or frame.size == 0
        or frame.dtype != np.uint8
        or frame.ndim != 3
        or frame.shape[2] != 3
    ):
        raise ValueError("Frame must be a non-empty uint8 BGR image.")

    model, preprocess, _ = get_clip()

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = preprocess(Image.fromarray(rgb)).unsqueeze(0)

    with torch.inference_mode():
        features = model.encode_image(image)

    return normalize_embedding(features)


def embed_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Search text must not be empty.")

    model, _, tokenizer = get_clip()
    tokens = tokenizer([text.strip()])

    with torch.inference_mode():
        features = model.encode_text(tokens)

    return normalize_embedding(features)