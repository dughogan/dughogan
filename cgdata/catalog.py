"""Build the dataset manifest from every shot's meta.json.

Writes manifest.parquet (one row per clip) and passes.parquet (one row per
clip x EXR layer) into the catalog directory.

Usage:
    python -m cgdata.catalog LIBRARY/cg --out LIBRARY/catalog
"""

import argparse
import json
from pathlib import Path

import pandas as pd


def build(library, out):
    rows, pass_rows = [], []
    for meta_path in sorted(Path(library).glob("*/meta.json")):
        m = json.loads(meta_path.read_text())
        rows.append({
            "id": m["id"],
            "path": str(meta_path.parent.relative_to(library)),
            "type": m["type"],
            "style": m["style"],
            "environment": m["environment"],
            "hero": m["hero"],
            "camera_move": m["camera_move"],
            "time_of_day": m["time_of_day"],
            "width": m["resolution"][0],
            "height": m["resolution"][1],
            "fps": m["fps"],
            "frames": m["frame_range"][1] - m["frame_range"][0] + 1,
            "duration_s": m["duration_s"],
            "focal_mm": m["camera"]["focal_mm"],
            "samples": m["samples"],
            "qa_passed": m["qa"]["passed"],
            "light_rebuild_error": m["qa"]["worst"]["light_rebuild_error"],
            "lightgroup_rebuild_error": m["qa"]["worst"]["lightgroup_rebuild_error"],
            "comp_rendered": m["comp"]["rendered"],
            "bytes": sum(f["bytes"] for f in m["files"]),
            "ai_training_permitted": m["rights"]["ai_training_permitted"],
            "seed": m["spec"]["seed"],
        })
        for part in ("light", "data"):
            for layer in m["exr"][part]["layers"]:
                pass_rows.append({
                    "id": m["id"],
                    "file": m["exr"][part]["file"],
                    "layer": layer,
                    "precision": m["exr"][part]["precision"],
                    "channels": m["exr"]["channels_per_layer"].get(layer),
                })
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = pd.DataFrame(rows)
    manifest.to_parquet(out / "manifest.parquet", index=False)
    pd.DataFrame(pass_rows).to_parquet(out / "passes.parquet", index=False)
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    m = build(args.library, args.out)
    if m.empty:
        print("catalog: no meta.json files found")
        return
    print(f"catalog: {len(m)} clips, {m['duration_s'].sum() / 3600:.3f} h, "
          f"{m['bytes'].sum() / 1e9:.2f} GB, {int(m['qa_passed'].sum())} passed QA")
    print(m.groupby(["style", "environment"]).size().to_string())


if __name__ == "__main__":
    main()
