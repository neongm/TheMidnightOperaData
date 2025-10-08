#!/usr/bin/env python3
# tools/build_atlases.py
# Deterministic atlas builder with:
# - per-folder simplified or explicit config
# - strict validation (schema, bounds, duplicates)
# - safe placeholder handling (loaded once, copied)
# - deterministic folder order (utf-8 byte sort)
# - filename path traversal protection
#
# Exits with non-zero on serious errors so CI fails visibly.

import os
import sys
import json
from typing import Dict, List, Any, Optional
from PIL import Image, UnidentifiedImageError

# --- Constants / limits ---
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "atlases_src")
OUT_DIR = os.path.join(ROOT, "atlases")

MAX_CANVAS = 2048         # per audit: enforce maximum canvas size
DEFAULT_CANVAS = 2048
DEFAULT_SLOT = 512
DEFAULT_COLS = 4
DEFAULT_ROWS = 4

# --- Helpers -----------------------------------------------------------------
def err(msg: str):
    print(f"[ERROR] {msg}", file=sys.stderr)

def warn(msg: str):
    print(f"[WARN] {msg}")

def safe_open_image(path: str) -> Optional[Image.Image]:
    """Open and return a persistent Image (or None on failure)."""
    try:
        img = Image.open(path)
        return img.convert("RGBA")
    except UnidentifiedImageError as e:
        err(f"Unrecognized image file '{path}': {e}")
    except Exception as e:
        err(f"Failed opening image '{path}': {e}")
    return None

def is_safe_filename(name: str) -> bool:
    """Reject filenames that attempt path traversal or absolute paths."""
    if not isinstance(name, str) or name == "":
        return False
    if name.startswith("/") or name.startswith("\\"):
        return False
    if ".." in name:
        return False
    if "/" in name or "\\" in name:
        return False
    return True

# --- Validation --------------------------------------------------------------
def validate_slots(cfg: Dict[str, Any]) -> None:
    """
    Validate the config dict: types, ranges, canvas limits, uniqueness, and slot bounds.
    Raises ValueError on invalid config.
    """
    canvas_w = cfg.get("canvas_width")
    canvas_h = cfg.get("canvas_height")
    if not isinstance(canvas_w, int) or not isinstance(canvas_h, int):
        raise ValueError("canvas_width and canvas_height must be integers.")
    if canvas_w <= 0 or canvas_h <= 0:
        raise ValueError("canvas dimensions must be positive.")
    if canvas_w > MAX_CANVAS or canvas_h > MAX_CANVAS:
        raise ValueError(f"canvas dimensions must be <= {MAX_CANVAS}.")

    slots = cfg.get("slots")
    if not isinstance(slots, list) or len(slots) == 0:
        raise ValueError("slots must be a non-empty list after config processing.")

    seen_indices = set()
    for s in slots:
        if not isinstance(s, dict):
            raise ValueError("each slot entry must be an object/dict.")
        idx = s.get("index")
        x = s.get("x"); y = s.get("y"); w = s.get("w"); h = s.get("h")
        if not isinstance(idx, int) or idx < 1:
            raise ValueError("slot 'index' must be integer >= 1.")
        if idx in seen_indices:
            raise ValueError(f"duplicate slot index detected: {idx}")
        seen_indices.add(idx)
        for name, val in (("x", x), ("y", y), ("w", w), ("h", h)):
            if not isinstance(val, int):
                raise ValueError(f"slot {idx} property '{name}' must be integer.")
        if w <= 0 or h <= 0:
            raise ValueError(f"slot {idx} must have positive width/height.")
        if x < 0 or y < 0 or (x + w) > canvas_w or (y + h) > canvas_h:
            raise ValueError(f"slot {idx} bounds exceed canvas: x={x},y={y},w={w},h={h}, canvas={canvas_w}x{canvas_h}")

        filename = s.get("filename")
        if filename is not None:
            if not is_safe_filename(filename):
                raise ValueError(f"slot {idx} filename is unsafe: '{filename}'")

# --- Config loading ---------------------------------------------------------
def generate_grid_slots(cols: int, rows: int, slot_w: int, slot_h: int) -> List[Dict[str, Any]]:
    slots = []
    for i in range(rows * cols):
        col = i % cols
        row = i // cols
        slots.append({
            "index": i + 1,
            "x": col * slot_w,
            "y": row * slot_h,
            "w": slot_w,
            "h": slot_h,
            "filename": f"{i + 1}.png"
        })
    return slots

def load_config(folder: str) -> Dict[str, Any]:
    """
    Load config.json if present and normalize to a dict with:
    { canvas_width, canvas_height, slots: [ {index,x,y,w,h,filename?}, ... ] }
    Performs basic parsing; detailed validation is done in validate_slots().
    """
    config_path = os.path.join(folder, "config.json")
    if not os.path.isfile(config_path):
        # default grid
        return {
            "canvas_width": DEFAULT_CANVAS,
            "canvas_height": DEFAULT_CANVAS,
            "slots": generate_grid_slots(DEFAULT_COLS, DEFAULT_ROWS, DEFAULT_SLOT, DEFAULT_SLOT)
        }

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        raise ValueError(f"failed to parse config.json: {e}")

    # If explicit slots provided, use them (explicit mode)
    if isinstance(raw, dict) and "slots" in raw and isinstance(raw["slots"], list):
        canvas_w = raw.get("canvas_width", DEFAULT_CANVAS)
        canvas_h = raw.get("canvas_height", DEFAULT_CANVAS)
        normalized_slots = []
        for s in raw["slots"]:
            # Copy only expected fields; missing filename is OK
            normalized_slots.append({
                "index": int(s["index"]) if "index" in s else None,
                "x": int(s["x"]),
                "y": int(s["y"]),
                "w": int(s["w"]),
                "h": int(s["h"]),
                "filename": s.get("filename")
            })
        cfg = {"canvas_width": int(canvas_w), "canvas_height": int(canvas_h), "slots": normalized_slots}
        validate_slots(cfg)
        return cfg

    # Simplified grid mode: accept cols/rows/slot_width/slot_height
    cols = int(raw.get("cols", DEFAULT_COLS))
    rows = int(raw.get("rows", DEFAULT_ROWS))
    slot_w = int(raw.get("slot_width", DEFAULT_SLOT))
    slot_h = int(raw.get("slot_height", DEFAULT_SLOT))
    canvas_w = int(raw.get("canvas_width", cols * slot_w))
    canvas_h = int(raw.get("canvas_height", rows * slot_h))

    # Quick bounds check before generating
    if canvas_w > MAX_CANVAS or canvas_h > MAX_CANVAS:
        raise ValueError(f"generated canvas ({canvas_w}x{canvas_h}) exceeds MAX_CANVAS {MAX_CANVAS}.")

    slots = generate_grid_slots(cols, rows, slot_w, slot_h)
    cfg = {"canvas_width": canvas_w, "canvas_height": canvas_h, "slots": slots}
    validate_slots(cfg)
    return cfg

# --- Atlas build ------------------------------------------------------------
def build_atlas(atlas_name: str, src_folder: str, out_folder: str):
    os.makedirs(out_folder, exist_ok=True)

    # Load config (may raise ValueError)
    cfg = load_config(src_folder)
    canvas_w = cfg["canvas_width"]
    canvas_h = cfg["canvas_height"]
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    placeholder_path = os.path.join(src_folder, "placeholder.png")
    placeholder_img = None
    if os.path.isfile(placeholder_path):
        placeholder_img = safe_open_image(placeholder_path)
        if placeholder_img is None:
            raise RuntimeError(f"placeholder.png present but could not be opened in '{atlas_name}'")
    # placeholder_img left as None if missing

    slots = sorted(cfg["slots"], key=lambda s: int(s["index"]))  # deterministic slot order

    mapping = {}
    for slot in slots:
        idx = int(slot["index"])
        filename = slot.get("filename") or f"{idx}.png"

        # Safety: reject dangerous filenames
        if not is_safe_filename(filename):
            raise ValueError(f"unsafe filename '{filename}' in atlas '{atlas_name}' slot {idx}")

        src_path = os.path.join(src_folder, filename)
        img = None
        source_used = None

        if os.path.isfile(src_path):
            img = safe_open_image(src_path)
            if img is None:
                raise RuntimeError(f"Failed opening '{src_path}' for atlas '{atlas_name}'.")
            source_used = filename
        elif placeholder_img is not None:
            img = placeholder_img.copy()  # use a fresh copy for deterministic mutations
            source_used = "placeholder.png"
        else:
            # leave transparent slot
            source_used = None
            warn(f"Atlas '{atlas_name}': missing '{filename}' and no placeholder -> leaving transparent slot {idx}.")

        # Resize & paste if we have an image
        if img is not None:
            # resize-to-cover then center-crop
            w_slot = int(slot["w"]); h_slot = int(slot["h"])
            w_img, h_img = img.size
            scale = max(w_slot / w_img, h_slot / h_img)
            new_w = int(round(w_img * scale)); new_h = int(round(h_img * scale))
            img = img.resize((new_w, new_h), resample=Image.LANCZOS)
            left = (new_w - w_slot) // 2
            top = (new_h - h_slot) // 2
            img = img.crop((left, top, left + w_slot, top + h_slot))
            canvas.paste(img, (int(slot["x"]), int(slot["y"])), img)

        mapping[str(idx)] = {
            "x": int(slot["x"]), "y": int(slot["y"]),
            "w": int(slot["w"]), "h": int(slot["h"]),
            "source": source_used
        }

    out_png = os.path.join(out_folder, f"atlas_{atlas_name}.png")
    out_json = os.path.join(out_folder, f"atlas_{atlas_name}.json")
    canvas.save(out_png, format="PNG")
    with open(out_json, "w", encoding="utf-8") as jf:
        json.dump({"name": atlas_name, "width": canvas_w, "height": canvas_h, "slots": mapping}, jf, indent=2)

    print(f"[OK] Built atlas '{atlas_name}' -> {os.path.relpath(out_png)}")

# --- Main -------------------------------------------------------------------
def main():
    if not os.path.isdir(SRC_DIR):
        err(f"Source folder not found: {SRC_DIR}")
        sys.exit(1)

    try:
        # Deterministic folder order using utf-8 byte sorting as requested
        atlas_folders = sorted(
            [d for d in os.listdir(SRC_DIR) if os.path.isdir(os.path.join(SRC_DIR, d))],
            key=lambda x: x.encode('utf-8')
        )
    except Exception as e:
        err(f"Failed to list atlas folders: {e}")
        sys.exit(1)

    if not atlas_folders:
        warn("No atlas folders found in atlases_src/. Nothing to build.")
        sys.exit(0)

    for name in atlas_folders:
        src = os.path.join(SRC_DIR, name)
        try:
            build_atlas(name, src, OUT_DIR)
        except ValueError as ve:
            err(f"Config validation error for atlas '{name}': {ve}")
            sys.exit(1)
        except RuntimeError as re:
            err(f"Runtime error building atlas '{name}': {re}")
            sys.exit(1)
        except Exception as e:
            err(f"Unexpected error building atlas '{name}': {e}")
            sys.exit(1)

    print("[DONE] All atlases processed successfully.")

if __name__ == "__main__":
    main()
