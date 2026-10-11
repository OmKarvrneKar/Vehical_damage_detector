"""Convert a Roboflow TensorFlow-format export into Ultralytics YOLO format.

Roboflow's TensorFlow export contains per-split folders with images plus an
``_annotations.csv`` whose columns are ``filename,width,height,class,xmin,ymin,xmax,ymax``
(absolute pixel coordinates and numeric class ids). YOLO needs one ``.txt`` per image with
normalised ``class cx cy w h`` rows and an ``images/`` + ``labels/`` layout.

Usage:
  python backend/training/convert_roboflow_tf.py --src <extracted_export> --dst data/dataset
"""
import argparse
import csv
import shutil
from collections import defaultdict
from pathlib import Path

# Class-id order for the "Automobile Damage Detection" Roboflow project (0-13).
CLASSES = [
    "bonnet-dent", "boot-dent", "doorouter-dent", "fender-dent", "front-bumper-dent",
    "Front-windscreen-damage", "Headlight-damage", "quaterpanel-dent", "rear-bumper-dent",
    "Rear-windscreen-Damage", "roof-dent", "Runningboard-Damage", "Sidemirror-Damage",
    "Taillight-Damage",
]
SPLITS = {"train": "train", "valid": "val", "test": "test"}
IMG_EXT = {".jpg", ".jpeg", ".png"}


def _read_annotations(csv_path: Path):
    boxes = defaultdict(list)
    if not csv_path.exists():
        return boxes
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = {k.strip().lower(): v for k, v in row.items()}
            w, h = float(key["width"]), float(key["height"])
            x1, y1 = float(key["xmin"]), float(key["ymin"])
            x2, y2 = float(key["xmax"]), float(key["ymax"])
            cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
            bw, bh = (x2 - x1) / w, (y2 - y1) / h
            cx, cy = min(max(cx, 0.0), 1.0), min(max(cy, 0.0), 1.0)
            bw, bh = min(max(bw, 0.0), 1.0), min(max(bh, 0.0), 1.0)
            boxes[key["filename"]].append((int(key["class"]), cx, cy, bw, bh))
    return boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="path to the extracted Roboflow export")
    ap.add_argument("--dst", required=True, help="destination dataset root (e.g. data/dataset)")
    a = ap.parse_args()

    src, dst = Path(a.src), Path(a.dst)
    if not src.is_dir():
        raise SystemExit(f"Source folder not found: {src}")

    total_boxes = 0
    for split, yolo_split in SPLITS.items():
        split_dir = src / split
        if not split_dir.is_dir():
            print(f"skip missing split: {split_dir}")
            continue
        annotations = _read_annotations(split_dir / "_annotations.csv")
        img_out = dst / "images" / yolo_split
        lbl_out = dst / "labels" / yolo_split
        img_out.mkdir(parents=True, exist_ok=True)
        lbl_out.mkdir(parents=True, exist_ok=True)

        n_img = n_box = 0
        for img in split_dir.iterdir():
            if img.suffix.lower() not in IMG_EXT:
                continue
            shutil.copy2(img, img_out / img.name)
            rows = annotations.get(img.name, [])
            with (lbl_out / f"{img.stem}.txt").open("w", encoding="utf-8") as f:
                for cls, cx, cy, bw, bh in rows:
                    f.write(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
            n_img += 1
            n_box += len(rows)
        total_boxes += n_box
        print(f"{split:>5} -> images/{yolo_split}: {n_img} images, {n_box} boxes")

    print(f"done. total boxes: {total_boxes}")


if __name__ == "__main__":
    main()
