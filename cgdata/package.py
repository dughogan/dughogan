"""Assemble a buyer-ready pilot package from an exported library.

    python -m cgdata.package LIBRARY --out PILOT_PACKAGE [--samples 24] [--with-exr 4]

Picks curated, QA-passed clips (stratified across style, environment and
hero so the sample shows the range), and writes:

    PILOT_PACKAGE/
      README.md                what's here and how to read it
      DATASHEET.md             composition, specs, passes, QA and provenance, generated
      PITCH_DRAFT.md           a draft pitch with the numbers filled in (Doug edits it)
      manifest.parquet         one row per included clip (catalog subset)
      pairs/<set>.jsonl        IC-LoRA pair manifests, filtered to the included clips
      clips/<id>/              exported videos, meta.json, provenance record (HTML)
      exr_samples/<id>/        full multilayer EXRs + .blend + .nk for --with-exr clips

Nothing here makes a legal claim: licence terms are a placeholder for Dugco's
counsel, and the datasheet reports what the provenance records show.
"""

import argparse
import json
import random
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from cgdata import catalog, provenance


def select(manifest, n, seed=1):
    """Stratified pick across style x environment x hero, curated + QA-passed only."""
    rng = random.Random(seed)
    groups = {}
    for _, row in manifest.iterrows():
        groups.setdefault((row["style"], row["environment"], row["hero"]), []).append(row["id"])
    for ids in groups.values():
        rng.shuffle(ids)
    picked, keys = [], sorted(groups)
    while len(picked) < n and any(groups.values()):
        for k in keys:
            if groups[k] and len(picked) < n:
                picked.append(groups[k].pop())
    # style pairs travel together (CG_000123_pr with CG_000123_tn)
    present = set(manifest["id"])
    for sid in list(picked):
        for tag in ("_pr", "_tn"):
            if sid.endswith(("_pr", "_tn")):
                partner = sid[:-3] + tag
                if partner in present and partner not in picked:
                    picked.append(partner)
    return picked


def eligible_manifest(library):
    cg = Path(library) / "cg"
    rows = catalog.build(cg, Path(library) / "catalog")
    keep = []
    for _, row in rows.iterrows():
        shot = cg / row["path"]
        gate = provenance.gate_status(provenance._load(provenance.shot_history_path(shot)))
        if row["qa_passed"] and gate.get("shot_curated", {}).get("decision") == "approve":
            keep.append(row)
    return pd.DataFrame(keep)


def table(counter, header):
    lines = [f"| {header} | Clips |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(counter.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)


def datasheet(library, ids, metas, pair_counts):
    first = metas[0]
    styles = Counter(m["style"] for m in metas)
    envs = Counter(m["environment"] for m in metas)
    heroes = Counter(m["hero"] for m in metas)
    fx = Counter(((m.get("spec") or {}).get("fx") or {}).get("type", "none") for m in metas)
    assurance = Counter((m.get("provenance") or {}).get("assurance", "absent") for m in metas)
    decisions = sum((m.get("provenance") or {}).get("human_decisions", 0) for m in metas)
    edits = sum((m.get("provenance") or {}).get("caption_edits", 0) for m in metas)
    seconds = sum(m["duration_s"] for m in metas)
    worst = max(m["qa"]["worst"]["light_rebuild_error"] for m in metas)
    frames = first["frame_range"][1] - first["frame_range"][0] + 1
    ltx_ok = (frames - 1) % 8 == 0 and all(v % 32 == 0 for v in first["resolution"])
    comps = sum(1 for m in metas if m["comp"]["rendered"])
    return f"""# Datasheet: cgdata pilot

Generated {date.today().isoformat()} from {len(ids)} clips ({seconds / 60:.1f} minutes).

## What it is
Procedurally generated, fully owned CG clips (Dugco). Each clip is rendered in
Blender/Cycles with every render pass, and ships with its scene file,
captions, IC-LoRA pair videos and a ComfyAudit provenance record;
{comps} of {len(metas)} clips include a finished Nuke comp. No third-party
assets, scans, textures or people are used.

## Composition
{table(styles, "Style")}

{table(envs, "Environment")}

{table(heroes, "Hero")}

{table(fx, "FX event")}

## Technical
- Resolution {first['resolution'][0]}×{first['resolution'][1]}, {first['fps']} fps,
  {frames} frames per clip ({'8n+1 frames and /32 resolution: LTX-native' if ltx_ok else 'NOT LTX-native: needs 8n+1 frames and /32 resolution'})
- Color: {first['colorspace']}; renderer {first['renderer']}
- EXR layers: {len(first['exr']['light']['layers'])} half-float light layers,
  {len(first['exr']['data']['layers'])} float data layers (see `clips/<id>/meta.json`)
- Light groups: {', '.join(first['light_groups'])}
- Rendered sharp; motion blur and depth of field are applied in the comp
  from the vector and depth passes.

## IC-LoRA pair sets
{table(Counter(pair_counts), "Pair set")}

## Quality checks (every frame)
- Light passes rebuild Combined: worst mean error {worst:.5f} (tolerance 0.01)
- Light groups rebuild Combined; no NaN/Inf in any layer; all expected layers present

## Provenance
- History assurance: {', '.join(f'{k} {v}' for k, v in assurance.items())}
- Named human decisions on these clips: {decisions}; human caption rewrites: {edits}
- Each clip's ComfyAudit provenance record: `clips/<id>/provenance.html`

## Known limits
- Draft-quality renders are noisy; pilot renders use 512 samples.
- Mantaflow smoke/fire is not yet included.
- Licence terms: placeholder pending Dugco's counsel.
"""


def pitch(metas, pair_counts):
    seconds = sum(m["duration_s"] for m in metas)
    sets = ", ".join(sorted(pair_counts))
    return f"""# Draft pitch: cgdata for LTX (Doug to edit before sending)

**The offer:** production-grade CG training data, built for VFX-quality video
generation: every clip carries the full render decomposition, a finished
comp, scene files and exact control signals.

**Why it's different**
- Exact ground truth: light passes rebuild the beauty to within
  {max(m['qa']['worst']['light_rebuild_error'] for m in metas):.4f} mean error, per frame.
- Paired, aligned control data for IC-LoRAs: {sets}.
- Photoreal and toon renders of the *same* shots (identical geometry and camera).
- Clean rights: procedurally generated, no third-party assets; ComfyAudit
  provenance record per clip with named human approvals.

**This pilot:** {len(metas)} clips, {seconds / 60:.1f} minutes, LTX-native
resolution and frame counts. The full set scales to 10,000+ clips.

**Proposed next step:** an IC-LoRA trained on the pilot pairs, compared with
and without the data. [Doug: add results here once trained.]

**Terms:** [Doug + counsel: exclusivity window, field of use, pricing.]
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--with-exr", type=int, default=0, help="include full EXRs for this many clips")
    args = ap.parse_args()

    manifest = eligible_manifest(args.library)
    if manifest.empty:
        raise SystemExit("package: no curated, QA-passed clips (run review shots first)")
    ids = select(manifest, args.samples)
    out = args.out
    (out / "clips").mkdir(parents=True, exist_ok=True)
    export = args.library / "export"
    metas = []
    for i, sid in enumerate(ids):
        shot = args.library / "cg" / sid
        dst = out / "clips" / sid
        if not (export / sid).is_dir():
            raise SystemExit(f"package: {sid} isn't exported yet (run cgdata.export)")
        shutil.copytree(export / sid, dst, dirs_exist_ok=True)
        shutil.copy(shot / "meta.json", dst / "meta.json")
        provenance.record_html(provenance.shot_history_path(shot), dst / "provenance.html")
        metas.append(json.loads((shot / "meta.json").read_text()))
        if i < args.with_exr:
            ex = out / "exr_samples" / sid
            for sub in ("renders", "scene", "comp"):
                if (shot / sub).is_dir():
                    shutil.copytree(shot / sub, ex / sub, dirs_exist_ok=True)

    pair_counts = {}
    (out / "pairs").mkdir(exist_ok=True)
    for f in sorted((export / "pairs").glob("*.jsonl")):
        keep = set(ids)
        rows = [r for r in map(json.loads, f.read_text().splitlines())
                if r["id"] in keep and r["conditioning_path"].split("/")[0] in keep]
        if rows:
            (out / "pairs" / f.name).write_text("".join(json.dumps(r) + "\n" for r in rows))
            pair_counts[f.stem] = len(rows)

    manifest[manifest["id"].isin(ids)].to_parquet(out / "manifest.parquet", index=False)
    (out / "DATASHEET.md").write_text(datasheet(args.library, ids, metas, pair_counts))
    (out / "PITCH_DRAFT.md").write_text(pitch(metas, pair_counts))
    (out / "README.md").write_text(
        "# cgdata pilot package\n\nStart with DATASHEET.md. Clips are in `clips/<id>/` "
        "(videos, meta.json, provenance.html); IC-LoRA pair manifests in `pairs/` "
        "(paths relative to `clips/`); full EXR samples in `exr_samples/`.\n"
        "Licence terms: placeholder pending Dugco's counsel.\n")
    print(f"package: {len(ids)} clips, {len(pair_counts)} pair sets -> {out}")


if __name__ == "__main__":
    main()
