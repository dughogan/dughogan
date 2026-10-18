"""QA and cataloging for a rendered shot.

Checks every frame's EXRs, writes a pass contact sheet, and writes meta.json
(the per-clip record that goes into the dataset manifest).

Checks:
  - every expected layer is present
  - no NaN / Inf in any layer
  - light-pass rebuild == Combined:
        (DiffDir+DiffInd)*DiffCol + (GlossDir+GlossInd)*GlossCol
      + (TransDir+TransInd)*TransCol + VolumeDir + VolumeInd + Emit + Env
  - light-group rebuild == Combined: sum of Combined_<group>
  - exposure sanity (mean luminance, clipped / black fraction)

Usage:
    python -m cgdata.qa LIBRARY/cg/CG_000001
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import OpenEXR
from PIL import Image, ImageDraw

from cgdata.comp_params import make_comp_params

META_VERSION = 1

# Max mean relative error for a rebuild to pass. Half-float storage alone
# contributes ~1e-3; anything above this means a pass is missing or wrong.
REBUILD_TOLERANCE = 0.01

LIGHT_REBUILD = [
    ("DiffDir", "DiffInd", "DiffCol"),
    ("GlossDir", "GlossInd", "GlossCol"),
    ("TransDir", "TransInd", "TransCol"),
]
LIGHT_ADDITIVE = ["VolumeDir", "VolumeInd", "Emit", "Env"]
CONTACT_SHEET = ["Combined", "DiffDir", "DiffInd", "GlossDir", "TransDir", "Emit",
                 "DiffCol", "base_color", "Normal", "Depth", "Vector", "CryptoObject00",
                 "Combined_key", "Combined_fill", "Combined_rim", "Combined_env"]


def read_layers(path):
    """Read a (multi-part) multilayer EXR into {layer: HxWxC float32 array}."""
    layers = {}
    with OpenEXR.File(str(path), separate_channels=True) as f:
        for part in f.parts:
            for name, ch in part.channels.items():
                layer, _, chan = name.rpartition(".")
                layer = layer or part.name()
                layers.setdefault(layer, {})[chan] = ch.pixels.astype(np.float32)
    out = {}
    for layer, chans in layers.items():
        order = [c for c in ("R", "G", "B", "A", "r", "g", "b", "a", "X", "Y", "Z", "W", "V") if c in chans]
        order += [c for c in chans if c not in order]
        out[layer] = np.stack([chans[c] for c in order], axis=-1)
    return out


def rgb(a):
    return a[..., :3]


def rel_error(rebuilt, reference):
    denom = np.abs(reference).mean() + 1e-6
    return float(np.abs(rebuilt - reference).mean() / denom)


def luminance(a):
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def check_frame(layers, expected):
    result = {"missing_layers": sorted(set(expected) - set(layers))}
    bad = {k: int((~np.isfinite(v)).sum()) for k, v in layers.items()}
    result["nonfinite_pixels"] = {k: v for k, v in bad.items() if v}

    combined = rgb(layers["Combined"])
    rebuilt = np.zeros_like(combined)
    for direct, indirect, color in LIGHT_REBUILD:
        if direct in layers:
            rebuilt += (rgb(layers[direct]) + rgb(layers[indirect])) * rgb(layers[color])
    for name in LIGHT_ADDITIVE:
        if name in layers:
            rebuilt += rgb(layers[name])
    result["light_rebuild_error"] = rel_error(rebuilt, combined)

    groups = [k for k in layers if k.startswith("Combined_")]
    if groups:
        lg = sum(rgb(layers[k]) for k in groups)
        result["lightgroup_rebuild_error"] = rel_error(lg, combined)

    lum = luminance(combined)
    result["mean_luminance"] = float(lum.mean())
    result["clipped_fraction"] = float((lum > 1.0).mean())
    result["black_fraction"] = float((lum < 1e-4).mean())
    return result


def to_display(a, name):
    """Map a layer to an 8-bit RGB thumbnail for the contact sheet."""
    if name == "Depth":
        d = a[..., 0]
        finite = d[np.isfinite(d) & (d < 1e9)]
        lo, hi = (np.percentile(finite, [1, 99]) if finite.size else (0, 1))
        img = 1.0 - np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
        img = np.repeat(img[..., None], 3, -1)
    elif name == "Normal":
        img = rgb(a) * 0.5 + 0.5
    elif name == "Vector":
        img = np.clip(np.concatenate([a[..., :2] * 0.05 + 0.5, np.full_like(a[..., :1], 0.5)], -1), 0, 1)
    elif name.startswith("Crypto"):
        # Hash ID -> stable pseudo-random color.
        ids = a[..., 0].view(np.uint32) if a.dtype == np.float32 else a[..., 0].astype(np.float32).view(np.uint32)
        img = np.stack([((ids >> s) & 255) / 255.0 for s in (0, 8, 16)], -1)
    elif name in ("DiffCol", "GlossCol", "TransCol", "base_color"):
        img = np.clip(rgb(a), 0, 1) ** (1 / 2.2)
    else:
        img = np.clip(rgb(a), 0, 1) ** (1 / 2.2)  # simple display gamma
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def contact_sheet(layers, path, thumb_w=320):
    names = [n for n in CONTACT_SHEET if n in layers]
    h, w = layers["Combined"].shape[:2]
    th = int(h * thumb_w / w)
    cols = 4
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, rows * (th + 18)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        img = Image.fromarray(to_display(layers[name], name)).resize((thumb_w, th))
        x, y = (i % cols) * thumb_w, (i // cols) * (th + 18)
        sheet.paste(img, (x, y + 18))
        draw.text((x + 4, y + 3), name, fill=(220, 220, 220))
    sheet.save(path)


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def run(shot_dir, checksums=True):
    shot_dir = Path(shot_dir)
    spec = json.loads((shot_dir / "spec.json").read_text())
    scene = json.loads((shot_dir / "scene.json").read_text())
    shot_id = spec["shot_id"]
    r = spec["render"]
    expected_light = scene["exr_layers"]["light"]
    expected_data = scene["exr_layers"]["data"]

    frames = {}
    worst = {"light_rebuild_error": 0.0, "lightgroup_rebuild_error": 0.0}
    issues = []
    mid = (r["frame_start"] + r["frame_end"]) // 2
    for f in range(r["frame_start"], r["frame_end"] + 1):
        light_path = shot_dir / "renders" / f"{shot_id}_light.{f:04d}.exr"
        data_path = shot_dir / "renders" / f"{shot_id}_data.{f:04d}.exr"
        if not light_path.exists() or not data_path.exists():
            issues.append(f"frame {f}: missing EXR")
            continue
        layers = read_layers(light_path)
        layers.update(read_layers(data_path))
        res = check_frame(layers, expected_light + expected_data)
        frames[f] = res
        for k in worst:
            if k in res:
                worst[k] = max(worst[k], res[k])
        if res["missing_layers"]:
            issues.append(f"frame {f}: missing layers {res['missing_layers']}")
        if res["nonfinite_pixels"]:
            issues.append(f"frame {f}: NaN/Inf in {sorted(res['nonfinite_pixels'])}")
        if f == mid:
            (shot_dir / "qa").mkdir(exist_ok=True)
            contact_sheet(layers, shot_dir / "qa" / f"{shot_id}_passes.png")
            channels = {k: v.shape[-1] for k, v in layers.items()}
            resolution = list(layers["Combined"].shape[1::-1])

    for k, v in worst.items():
        if v > REBUILD_TOLERANCE:
            issues.append(f"{k} {v:.4f} exceeds tolerance {REBUILD_TOLERANCE}")

    files = sorted(p for p in shot_dir.rglob("*") if p.is_file() and p.name != "meta.json")
    meta = {
        "meta_version": META_VERSION,
        "id": shot_id,
        "type": "cg_paired",
        "style": spec["style"],
        "environment": spec["environment"]["type"],
        "hero": spec["hero"]["type"],
        "camera_move": spec["camera"]["move"],
        "time_of_day": spec["lighting"]["time_of_day"],
        "resolution": resolution if frames else r["resolution"],
        "fps": r["fps"],
        "frame_range": [r["frame_start"], r["frame_end"]],
        "duration_s": round((r["frame_end"] - r["frame_start"] + 1) / r["fps"], 3),
        "colorspace": scene["colorspace"],
        "renderer": f"Cycles (Blender {scene['blender_version']})",
        "samples": r["samples"],
        "exr": {
            "light": {"file": f"renders/{shot_id}_light.####.exr", "precision": "half", "layers": expected_light},
            "data": {"file": f"renders/{shot_id}_data.####.exr", "precision": "float", "layers": expected_data},
            "channels_per_layer": channels if frames else {},
        },
        "light_groups": scene["light_groups"],
        "lights": scene["lights"],
        "objects": scene["objects"],
        "camera": scene["camera"],
        "render_seconds_per_frame": scene.get("render_seconds_per_frame"),
        "comp": {
            "script": f"comp/{shot_id}_comp.nk",
            "final": f"final/{shot_id}_final.####.exr",
            "rendered": (shot_dir / "final").is_dir(),
            "params": make_comp_params(spec),
        },
        "qa": {
            "passed": not issues,
            "issues": issues,
            "rebuild_tolerance": REBUILD_TOLERANCE,
            "worst": worst,
            "frames": frames,
        },
        "rights": {
            "owner": "TBD",
            "origin": "procedurally generated; no third-party assets, textures or scans",
            "people_present": False,
            "third_party_assets": [],
            "ai_training_permitted": True,
        },
        "files": [
            {"path": str(p.relative_to(shot_dir)), "bytes": p.stat().st_size,
             **({"sha256": sha256(p)} if checksums else {})}
            for p in files
        ],
        "spec": spec,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (shot_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shot_dirs", nargs="+", type=Path)
    ap.add_argument("--no-checksums", action="store_true")
    args = ap.parse_args()
    failed = 0
    for d in args.shot_dirs:
        meta = run(d, checksums=not args.no_checksums)
        q = meta["qa"]
        status = "PASS" if q["passed"] else "FAIL"
        print(f"{meta['id']}: {status}  light_rebuild={q['worst']['light_rebuild_error']:.5f}  "
              f"lightgroup_rebuild={q['worst']['lightgroup_rebuild_error']:.5f}")
        for issue in q["issues"]:
            print(f"  - {issue}")
        failed += not q["passed"]
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
