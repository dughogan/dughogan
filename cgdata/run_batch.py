"""Generate, render, QA, comp and catalog a batch of shots.

    python -m cgdata.run_batch --count 500 --seed 1 --quality pilot \
        --library LIBRARY --blender /path/to/blender [--nuke /path/to/Nuke16.0]

Each stage is idempotent per shot (skipped when its outputs exist), so a
batch can be stopped and resumed, or split across machines by seed range.

Overnight window: `--stop-at 07:00` stops starting new shots once that local
time is reached (the shot in progress finishes). Start it from cron at 22:00:

    0 22 * * * cd /path/to/repo && python -m cgdata.run_batch --count 500 --seed 1 \
        --library /mnt/LIBRARY --blender /opt/blender/blender --stop-at 07:00 >> /mnt/LIBRARY/batch.log 2>&1

Re-running the same command each night picks up where the last night ended.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from cgdata import catalog, provenance, qa
from cgdata.spec import QUALITY, make_spec

ROOT = Path(__file__).resolve().parent


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd]).returncode


def stop_time(hhmm):
    """Next occurrence of local time HH:MM (tomorrow if already past today)."""
    h, m = map(int, hhmm.split(":"))
    now = datetime.now()
    stop = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return stop if stop > now else stop + timedelta(days=1)


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
    ap.add_argument("--stop-at", default=None, metavar="HH:MM",
                    help="local time after which no new shot is started (e.g. 07:00)")
    ap.add_argument("--no-provenance", action="store_true",
                    help="skip ComfyAudit history (tests only: clips without it can't be sold)")
    args = ap.parse_args()
    if not args.no_provenance:
        provenance.comfyaudit()  # fail now, not after a night of rendering
    deadline = stop_time(args.stop_at) if args.stop_at else None

    shots_dir = args.library / "cg"
    spec_dir = args.library / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    build = ROOT / "blender" / "build_shot.py"
    failed = []

    stopped_early = False
    for seed in range(args.seed, args.seed + args.count):
        if deadline and datetime.now() >= deadline:
            stopped_early = True
            print(f"run_batch: reached --stop-at {args.stop_at}; resuming next run at seed {seed}")
            break
        spec = make_spec(seed, args.quality)
        spec_path = spec_dir / f"{spec['shot_id']}.json"
        spec_path.write_text(json.dumps(spec, indent=2))
        shot_dir = shots_dir / spec["shot_id"]

        changed = False
        if not (shot_dir / "scene.json").exists():
            changed = True
            if args.blender:
                cmd = [args.blender, "-b", "--factory-startup", "-P", build, "--"]
            else:
                cmd = [sys.executable, build]
            if run(cmd + ["--spec", spec_path, "--out", shots_dir, "--device", args.device]):
                failed.append((spec["shot_id"], "render"))
                continue

        if args.nuke and not (shot_dir / "final").is_dir():
            changed = True
            if run([args.nuke, "-t", ROOT / "nuke" / "build_comp.py", shot_dir]):
                failed.append((spec["shot_id"], "comp"))

        # QA hashes every file, so it runs only when something new was made.
        meta_path = shot_dir / "meta.json"
        meta = qa.run(shot_dir) if changed or not meta_path.exists() else json.loads(meta_path.read_text())
        if not meta["qa"]["passed"]:
            failed.append((spec["shot_id"], "qa: " + "; ".join(meta["qa"]["issues"])))

        if not args.no_provenance:
            steps = provenance.recorded_steps(shot_dir)
            if "render" not in steps:
                provenance.record_render(shot_dir, meta)
            if "comp" not in steps and meta["comp"]["rendered"]:
                provenance.record_comp(shot_dir, meta)
            provenance.refresh_meta(shot_dir)

    catalog.build(shots_dir, args.library / "catalog")
    done = sum(1 for p in shots_dir.glob("*/meta.json"))
    print(f"run_batch: {done} shots in library; {len(failed)} problems this run"
          + (" (stopped for the night)" if stopped_early else ""))
    for shot_id, why in failed:
        print(f"  {shot_id}: {why}")


if __name__ == "__main__":
    main()
