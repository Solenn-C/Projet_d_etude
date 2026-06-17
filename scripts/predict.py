"""
Prédit la classe d'une image de vêtement avec le modèle ONNX exporté.

Usage :
    python scripts/predict.py image.jpg
    python scripts/predict.py image.jpg --top 3
    python scripts/predict.py chemin/vers/dossier/  # prédit toutes les images du dossier
"""

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import requests
from PIL import Image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_PATH      = Path("model/fashion_classifier.onnx")
CLASS_NAMES_PATH = Path("model/class_names.json")
IMG_SIZE        = 224

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def load_image(source: str) -> Image.Image:
    if source.startswith("http://") or source.startswith("https://"):
        resp = requests.get(source, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    return Image.open(source).convert("RGB")


def preprocess(image_path) -> np.ndarray:
    img = load_image(str(image_path))
    img = img.resize((IMG_SIZE, IMG_SIZE), Image.BILINEAR)
    arr = np.array(img, dtype=np.float32) / 255.0
    arr = (arr - MEAN) / STD
    arr = arr.transpose(2, 0, 1)          # HWC → CHW
    return arr[np.newaxis, ...]            # batch dimension


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


# ---------------------------------------------------------------------------
# Prédiction
# ---------------------------------------------------------------------------

def predict(image_path: Path, session: ort.InferenceSession, class_names: list[str], top_k: int = 1) -> list[tuple[str, float]]:
    input_tensor = preprocess(image_path)
    logits = session.run(None, {"image": input_tensor})[0][0]
    probs  = softmax(logits)
    top_idx = np.argsort(probs)[::-1][:top_k]
    return [(class_names[i], float(probs[i])) for i in top_idx]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Prédit la classe d'un vêtement")
    parser.add_argument("path", help="Image ou dossier d'images")
    parser.add_argument("--top", type=int, default=3, help="Nombre de classes à afficher (défaut : 3)")
    parser.add_argument("--model",  default=str(MODEL_PATH),       help="Chemin vers le fichier ONNX")
    parser.add_argument("--labels", default=str(CLASS_NAMES_PATH), help="Chemin vers class_names.json")
    return parser.parse_args()


def main():
    args = parse_args()

    model_path  = Path(args.model)
    labels_path = Path(args.labels)

    if not model_path.exists():
        print(f"Modèle introuvable : {model_path}")
        sys.exit(1)
    if not labels_path.exists():
        print(f"Fichier de classes introuvable : {labels_path}")
        sys.exit(1)

    with open(labels_path, encoding="utf-8") as f:
        class_names = json.load(f)

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    print(f"Modèle chargé : {model_path.name} ({len(class_names)} classes)\n")

    input_path = args.path
    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}

    if input_path.startswith("http://") or input_path.startswith("https://"):
        images = [input_path]
    elif Path(input_path).is_dir():
        images = [p for p in sorted(Path(input_path).iterdir()) if p.suffix.lower() in valid_exts]
        print(f"{len(images)} images trouvées dans {input_path}\n")
    elif Path(input_path).is_file():
        images = [Path(input_path)]
    else:
        print(f"Chemin introuvable : {input_path}")
        sys.exit(1)

    for img_path in images:
        label = img_path if isinstance(img_path, str) else img_path.name
        try:
            results = predict(img_path, session, class_names, top_k=args.top)
            print(f"{label}")
            for rank, (cls, prob) in enumerate(results, 1):
                bar = "█" * int(prob * 20)
                print(f"  {rank}. {cls:20s} {prob:6.1%}  {bar}")
            print()
        except Exception as e:
            print(f"  ✗ Erreur sur {label} : {e}\n")


if __name__ == "__main__":
    main()
