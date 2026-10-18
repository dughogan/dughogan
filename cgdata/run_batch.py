"""Generate, render, QA, comp and catalog a batch of shots.

    python -m cgdata.run_batch --count 500 --seed 1 --quality pilot \
        --library LIBRARY --blender /path/to/blender [--nuke /path/to/Nuke16.0]

Each stage is idempotent per shot (skipped when its outputs exist), so a
batch can be stopped and resumed, or split across machines by seed range.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from cgdata import catalog, qa
from cgdata.spec import QUALITY, make_spec

ROOT = Path(__file__).resolve().parent


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd]).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--quality", choices=sorted(QUALITY), default="pilot")
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--blender", default=None,
                    help="Blender executable; default runs build_shot.py with this Python (needs the bpy module)")
    ap.add_argument("--device", choices=["CPU", "GPU"], default="GPU")
    ap.add_argument("--nuke", default=None, help="Nuke executable; omit to skip the comp stage")
    args = ap.parse_args()

    shots_dir = args.library / "cg"
    spec_dir = args.library / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    build = ROOT / "blender" / "build_shot.py"
    failed = []

    for seed in range(args.seed, args.seed + args.count):
        spec = make_spec(seed, args.quality)
        spec_path = spec_dir / f"{spec['shot_id']}.json"
        spec_path.write_text(json.dumps(spec, indent=2))
        shot_dir = shots_dir / spec["shot_id"]

        if not (shot_dir / "scene.json").exists():
            if args.blender:
                cmd = [args.blender, "-b", "--factory-startup", "-P", build, "--"]
            else:
                cmd = [sys.executable, build]
            if run(cmd + ["--spec", spec_path, "--out", shots_dir, "--device", args.device]):
                failed.append((spec["shot_id"], "render"))
                continue

        if args.nuke and not (shot_dir / "final").is_dir():
            if run([args.nuke, "-t", ROOT / "nuke" / "build_comp.py", shot_dir]):
                failed.append((spec["shot_id"], "comp"))

        meta = qa.run(shot_dir)
        if not meta["qa"]["passed"]:
            failed.append((spec["shot_id"], "qa: " + "; ".join(meta["qa"]["issues"])))

    catalog.build(shots_dir, args.library / "catalog")
    print(f"run_batch: {args.count - len(failed)}/{args.count} shots clean")
    for shot_id, why in failed:
        print(f"  {shot_id}: {why}")


if __name__ == "__main__":
    main()
