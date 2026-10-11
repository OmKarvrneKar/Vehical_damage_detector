"""Train / evaluate the YOLO damage model, then copy the weights to a target path.

  pip install ultralytics
  python backend/training/train_model.py --epochs 50
  python backend/training/train_model.py --data data/dataset/damage14.yaml --target backend/models/damage_model_14.pt
  python backend/training/train_model.py --eval-only          # just print the metrics

Defaults are unchanged for the original 6-class dataset; pass --data/--target to train the
14-class dataset produced by convert_roboflow_tf.py without overwriting the app's model.
"""
import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "dataset" / "damage.yaml"
TARGET = ROOT / "backend" / "models" / "damage_model.pt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA), help="path to the dataset YAML")
    ap.add_argument("--target", default=str(TARGET), help="where to copy the best weights")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8, help="lower this if training runs out of memory")
    ap.add_argument("--workers", type=int, default=0, help="0 is safest on Windows")
    ap.add_argument("--device", default=None, help="e.g. cpu, 0, or 0,1 (auto-detected if omitted)")
    ap.add_argument("--name", default="damage", help="run subfolder under runs/")
    ap.add_argument("--base", default="yolov8n.pt", help="pretrained weights to fine-tune")
    ap.add_argument("--eval-only", action="store_true")
    a = ap.parse_args()

    target = Path(a.target)

    if a.eval_only:
        model = YOLO(str(target))
    else:
        model = YOLO(a.base)
        model.train(data=a.data, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, workers=a.workers,
                    device=a.device, project=str(ROOT / "runs"), name=a.name)
        best = Path(model.trainer.best)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(best, target)
        model = YOLO(str(target))
        print("Saved weights to", target)

    m = model.val(data=a.data).box
    p, r = float(m.mp), float(m.mr)
    print(f"Precision {p:.3f} | Recall {r:.3f} | F1 {2*p*r/max(p+r,1e-9):.3f} | mAP50 {m.map50:.3f} | mAP50-95 {m.map:.3f}")


if __name__ == "__main__":
    main()
