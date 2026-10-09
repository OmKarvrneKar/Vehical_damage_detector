"""Pipeline: validate -> preprocess -> crop vehicle -> recognise -> detect -> classify -> severity
-> parts -> cost -> price comparison -> recommendation.

Detection uses a trained YOLO model if backend/models/damage_model.pt exists (and `ultralytics`
is installed); otherwise it falls back to an OpenCV edge-density baseline so the app still runs.
"""
import time
from pathlib import Path
import cv2
import numpy as np
import config

_yolo = None
try:
    if config.MODEL_PATH.exists():
        from ultralytics import YOLO
        _yolo = YOLO(str(config.MODEL_PATH))
except Exception:
    _yolo = None

LABELS = {"scratch": "Scratch", "dent": "Dent", "crack": "Crack", "broken_part": "Broken Part",
          "broken_lamp": "Broken Part", "glass_damage": "Glass Damage", "broken_glass": "Glass Damage",
          "bumper_damage": "Bumper Damage", "severe": "Severe / Fully Damaged"}
COLORS = {"Scratch": (0, 165, 255), "Dent": (0, 0, 230), "Crack": (200, 0, 160), "Broken Part": (0, 60, 255),
          "Glass Damage": (220, 160, 0), "Bumper Damage": (0, 120, 255), "Severe / Fully Damaged": (0, 0, 160)}
LABOUR = {"Scratch": 1500, "Dent": 3500, "Crack": 4000, "Broken Part": 6000, "Glass Damage": 3000,
          "Bumper Damage": 5000, "Severe / Fully Damaged": 15000}
SEV_MULT = {"Minor": 1.0, "Moderate": 1.6, "Severe": 2.5, "None": 0}
VEHICLE_MULT = {"Sedan": 1.0, "Hatchback": 0.85, "SUV": 1.4, "Truck": 1.6, "Motorcycle": 0.5}
REPLACE_TYPES = {"Broken Part", "Glass Damage", "Crack", "Bumper Damage", "Severe / Fully Damaged"}
PART_PRICE = {"Bumper": 7500, "Headlamp / Tail-lamp": 9000, "Door panel": 14000,
              "Windshield / Window glass": 8500, "Rocker panel / Lower body": 5500}
VENDORS = [("Authorised dealer (OEM)", 1.00, "3-5 days"), ("Online marketplace", 0.70, "4-7 days"),
           ("Local aftermarket shop", 0.60, "1-2 days")]
ACTION = {"Scratch": "Polish / touch-up paint", "Dent": "Paintless dent repair or panel beating",
          "Crack": "Crack repair; replace the part if it spreads", "Broken Part": "Replace the part",
          "Glass Damage": "Replace the glass", "Bumper Damage": "Repair or replace the bumper",
          "Severe / Fully Damaged": "Full body-shop assessment; check insurance total-loss"}


def _stage(stages, name, t0):
    stages.append({"stage": name, "ms": round((time.time() - t0) * 1000)})
    return time.time()


def _thumb(img, path):
    s = 360 / max(img.shape[:2])
    cv2.imwrite(str(path), cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img)


def analyze(path: Path, out_dir: Path, rid: str):
    stages, t = [], time.time()
    # 1. validate & load (OpenCV)
    if not path.exists():
        raise ValueError("Image file path does not exist.")
    orig = cv2.imread(str(path))
    if orig is None:
        raise ValueError("Could not read the image. Use a valid JPG, JPEG or PNG file.")
    if min(orig.shape[:2]) < 100:
        raise ValueError("Image is too small (minimum 100 px). Use a clearer photo.")
    t = _stage(stages, "Validate & load image", t)

    # 2. preprocess: resize -> noise reduction -> brightness/contrast enhancement
    s = 900 / max(orig.shape[:2])
    resized = cv2.resize(orig, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else orig.copy()
    denoised = cv2.bilateralFilter(resized, 7, 40, 40)
    lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
    mean_l = float(lab[:, :, 0].mean())
    if mean_l < 90 or mean_l > 170:                         # brightness correction (poor lighting)
        gamma = np.clip(np.log(128 / 255) / np.log(max(mean_l, 1) / 255), 0.5, 2.0)
        lut = (np.linspace(0, 1, 256) ** gamma * 255).astype(np.uint8)
        lab[:, :, 0] = cv2.LUT(lab[:, :, 0], lut)
    lab[:, :, 0] = cv2.createCLAHE(2.0, (8, 8)).apply(lab[:, :, 0])
    enh = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    h, w = enh.shape[:2]
    steps = []
    for key, label, im in [("s1", "Original image", orig), ("s2", "Resize", resized),
                           ("s3", "Noise reduction", denoised), ("s4", "Enhancement & normalisation", enh)]:
        _thumb(im, out_dir / f"{rid}_{key}.jpg"); steps.append({"label": label, "file": f"{rid}_{key}.jpg"})
    t = _stage(stages, "Preprocess (resize, denoise, enhance)", t)

    # 3. isolate the vehicle (crop away background)
    (ox, oy, cw, ch), found = _find_vehicle(enh)
    crop = enh[oy:oy + ch, ox:ox + cw]
    warning = "" if found else "A vehicle could not be isolated clearly, so the whole image was analysed. Results may be unreliable."
    t = _stage(stages, "Vehicle region extraction", t)

    # 4. recognise vehicle
    vehicle = _recognise(cw, ch)
    t = _stage(stages, "Vehicle recognition", t)

    # 5. detect + classify damage (coordinates relative to the crop)
    dets = _yolo_detect(crop) if _yolo else _baseline_detect(crop)
    t = _stage(stages, "Damage detection & classification", t)

    # 6. severity
    area = sum(d["w"] * d["h"] for d in dets) / float(cw * ch)
    types = sorted({d["type"] for d in dets})
    if not dets:
        severity = "None"
    else:
        severity = "Minor" if area < 0.04 else "Moderate" if area < 0.12 else "Severe"
        if "Severe / Fully Damaged" in types:
            severity = "Severe"
        elif severity == "Minor" and set(types) & REPLACE_TYPES:
            severity = "Moderate"
    t = _stage(stages, "Severity assessment", t)

    # 7. parts, cost, recommendation
    parts = _parts(dets, cw, ch, severity)
    cost = _cost(dets, parts, severity, vehicle["body"])
    rec = _recommend(types, severity)
    t = _stage(stages, "Cost, parts & repair planning", t)

    # annotated image (map crop coords back to full image)
    ann = enh.copy()
    cv2.rectangle(ann, (ox, oy), (ox + cw, oy + ch), (80, 160, 60), 1)
    for d in dets:
        d["x"] += ox; d["y"] += oy
        c = COLORS.get(d["type"], (0, 0, 255))
        cv2.rectangle(ann, (d["x"], d["y"]), (d["x"] + d["w"], d["y"] + d["h"]), c, 3)
        cv2.putText(ann, d["type"], (d["x"] + 4, max(18, d["y"] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / f"{rid}_annotated.jpg"), ann)

    conf = round(float(np.mean([d["conf"] for d in dets])) * 100, 1) if dets else vehicle["confidence"]
    fallback_active = _yolo is None
    engine_name = "YOLO model" if not fallback_active else "OpenCV baseline (heuristic)"

    warnings_list = []
    if fallback_active:
        warnings_list.append("Heuristic detector active: Running OpenCV edge-density analysis because YOLO weights are not loaded. Scores are uncalibrated heuristics.")
    if not found:
        warnings_list.append("Vehicle could not be isolated clearly; full image was analyzed.")
    warning_text = " | ".join(warnings_list)

    return {"id": rid, "damaged": bool(dets), "vehicle": vehicle, "damages": dets, "damage_types": types,
            "severity": severity, "damage_area_pct": round(area * 100, 1), "confidence": conf,
            "parts": parts, "cost": cost, "recommendation": rec, "annotated": f"{rid}_annotated.jpg",
            "steps": steps, "stages": stages, "warning": warning_text,
            "fallback_active": fallback_active,
            "engine": engine_name}


def _find_vehicle(img):
    h, w = img.shape[:2]
    full = ((0, 0, w, h), False)
    k = 400 / max(h, w)
    small = cv2.resize(img, None, fx=k, fy=k) if k < 1 else img.copy()
    sh, sw = small.shape[:2]
    mask = np.zeros((sh, sw), np.uint8)
    rect = (int(sw * .03), int(sh * .06), int(sw * .94), int(sh * .88))
    try:
        cv2.grabCut(small, mask, rect, np.zeros((1, 65)), np.zeros((1, 65)), 3, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return full
    fg = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    ys, xs = np.where(fg > 0)
    if len(xs) == 0:
        return full
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    if (x1 - x0) * (y1 - y0) / float(sw * sh) < 0.25:
        return full
    sc = w / float(sw)
    pad = 6
    x, y = max(0, int(x0 * sc) - pad), max(0, int(y0 * sc) - pad)
    return (x, y, min(w - x, int((x1 - x0) * sc) + 2 * pad), min(h - y, int((y1 - y0) * sc) + 2 * pad)), True


def _recognise(w, h):
    ar = w / float(h)
    if _yolo is None:
        body = "Hatchback" if ar < 1.45 else "Sedan" if ar < 2.2 else "SUV"
        return {"label": f"Car ({body})", "body": body, "confidence": 70.0, "note": "Estimated from vehicle shape"}
    return {"label": "Car (Sedan)", "body": "Sedan", "confidence": 85.0, "note": ""}


def _baseline_detect(img):
    """Grid edge-density analysis: cells with unusually dense edges are damage candidates."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 70, 170)
    gx, gy = 14, 10
    ch, cw = max(1, h // gy), max(1, w // gx)
    dens = np.zeros((gy, gx))
    for i in range(gy):
        for j in range(gx):
            dens[i, j] = edges[i * ch:(i + 1) * ch, j * cw:(j + 1) * cw].mean() / 255
    z = (dens - dens.mean()) / (dens.std() + 1e-6)
    mask = ((z > 1.6) & (dens > 0.06)).astype(np.uint8)
    mask[:, :1] = 0; mask[:, -1:] = 0; mask[:1, :] = 0; mask[-1:, :] = 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for k in range(1, n):
        cx, cy, cwid, chei, cnt = stats[k]
        x, y, bw, bh = cx * cw, cy * ch, cwid * cw, chei * ch
        d = edges[y:y + bh, x:x + bw].mean() / 255
        elong = max(bw, bh) / max(1, min(bw, bh))
        if y + bh / 2 < h * 0.33 and d > 0.10:
            typ = "Glass Damage"
        elif cnt >= 12 and d > 0.20:
            typ = "Severe / Fully Damaged"
        elif elong >= 2.2 and d < 0.14:
            typ = "Scratch"
        elif d > 0.17:
            typ = "Broken Part" if cnt >= 5 else "Crack"
        else:
            typ = "Dent"
        out.append({"type": typ, "x": int(x), "y": int(y), "w": int(bw), "h": int(bh),
                    "conf": round(min(0.93, 0.55 + 0.08 * float(z[lab == k].max())), 3)})
    return sorted(out, key=lambda d: -d["w"] * d["h"])[:6]


def _yolo_detect(img):
    res = _yolo(img, verbose=False)[0]
    out = []
    for b in res.boxes:
        name = res.names[int(b.cls)].lower().replace(" ", "_")
        x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
        out.append({"type": LABELS.get(name, name.replace("_", " ").title()), "x": x1, "y": y1,
                    "w": x2 - x1, "h": y2 - y1, "conf": round(float(b.conf), 3)})
    return out


def _parts(dets, w, h, severity):
    found = {}
    for d in dets:
        cx, cy = (d["x"] + d["w"] / 2) / w, (d["y"] + d["h"] / 2) / h
        if cy < 0.35:
            p = "Windshield / Window glass"
        elif cx < 0.22 or cx > 0.78:
            p = "Bumper" if cy > 0.6 else "Headlamp / Tail-lamp"
        elif cy > 0.72:
            p = "Rocker panel / Lower body"
        else:
            p = "Door panel"
        needs = d["type"] in REPLACE_TYPES or severity == "Severe"
        found.setdefault(p, {"name": p, "damage": d["type"], "action": "Replace" if needs else "Repair"})
    for p in found.values():
        base = PART_PRICE[p["name"]]
        p["prices"] = ([{"vendor": v, "price": round(base * m, -1), "delivery": eta} for v, m, eta in VENDORS]
                       if p["action"] == "Replace" else [])
    return list(found.values())


def _cost(dets, parts, severity, body):
    if not dets:
        return {"min": 0, "max": 0, "labour": 0, "parts": 0}
    vm = VEHICLE_MULT.get(body, 1.0)
    labour = sum(LABOUR.get(d["type"], 4000) for d in dets) * SEV_MULT[severity] * vm
    parts_cost = sum(min(x["price"] for x in p["prices"]) for p in parts if p["prices"]) * vm
    total = labour + parts_cost
    return {"min": int(round(total * 0.85, -2)), "max": int(round(total * 1.2, -2)),
            "labour": int(round(labour, -2)), "parts": int(round(parts_cost, -2))}


def _recommend(types, severity):
    if not types:
        return "No visible damage detected. No repair needed."
    steps = "; ".join(f"{t}: {ACTION.get(t, 'Inspect at a workshop')}" for t in types)
    tail = {"Minor": "Cosmetic - can be done at a local workshop.",
            "Moderate": "Book a certified workshop; compare the part prices above.",
            "Severe": "Do not drive until inspected. Contact your insurer and get a body-shop quote."}[severity]
    return f"{steps}. {tail}"
