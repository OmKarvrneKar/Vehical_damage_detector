"""Train / evaluate the YOLO damage model, then copy the weights to backend/models/damage_model.pt

  pip install ultralytics
  python backend/training/train_model.py --epochs 50
  python backend/training/train_model.py --eval-only          # just print the metrics
"""
import argparse
import shutil
from pathlib import Path
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "dataset" / "damage.yaml"
TARGET = ROOT / "backend" / "models" / "damage_model.pt"

ap = argparse.ArgumentParser()
ap.add_argument("--epochs", type=int, default=50)
ap.add_argument("--imgsz", type=int, default=640)
ap.add_argument("--base", default="yolov8n.pt", help="pretrained weights to fine-tune")
ap.add_argument("--eval-only", action="store_true")
a = ap.parse_args()

if a.eval_only:
    model = YOLO(str(TARGET))
else:
    model = YOLO(a.base)
    model.train(data=str(DATA), epochs=a.epochs, imgsz=a.imgsz, project=str(ROOT / "runs"), name="damage")
    best = Path(model.trainer.best)
    TARGET.parent.mkdir(exist_ok=True)
    shutil.copy(best, TARGET)
    model = YOLO(str(TARGET))
    print("Saved weights to", TARGET)

m = model.val(data=str(DATA)).box
p, r = float(m.mp), float(m.mr)
print(f"Precision {p:.3f} | Recall {r:.3f} | F1 {2*p*r/max(p+r,1e-9):.3f} | mAP50 {m.map50:.3f} | mAP50-95 {m.map:.3f}")
