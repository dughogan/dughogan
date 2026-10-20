# Pilot roadmap

Goal: a 500-clip pilot that measurably improves LTX (new/better IC-LoRAs; the
full 10k+ set is the follow-on for LTX 2.5 base-model data). Owner: Dugco.

Work happens in nightly sessions (10pm–7am). Each night: take the next
unchecked items in order, commit and push to `cg-dataset-pipeline`, and
append a dated entry to `cgdata/updates/`. Items marked **[Doug]** need a
human decision or approval; nightly work prepares a review packet for them
and moves on to the next item that isn't blocked.

Human approvals are the authorship record: each one is logged through the
provenance gates (phase 1) once they exist.

## Phase 1: provenance
- [x] Review `dughogan/comfy_workflow_audit`: data model, signing/chaining, C2PA, delivery format (uses `core/history.py` as-is)
- [x] `cgdata/provenance.py`: gate events (asset approved, look locked, shot curated, comp finished) in Comfy Audit's format, hash-chained, referenced from meta.json
- [x] Review CLI: approve/reject with notes from a contact sheet, logged as a human event (`cgdata/review.py`)
- [ ] **[Doug]** Decide the two authorship gaps ComfyAudit's record flags (see updates/2026-10-19.md)
- [x] **[Doug]** Confirm the gate list and what counts as a creative decision (confirmed by Doug 2026-10-18: asset approved, look locked, shot curated, comp finished)

## Phase 2: asset library (minimum for 500 clips, 50–100 distinct scenes)
- [x] Modular city kit (facades, windows, roofs, street dressing): `blender/kits/city.py` v1, built with bmesh rather than geometry nodes; review sheet via `blender/kit_sheet.py`
- [ ] **[Doug]** Approve or send back `city_kit` v1 (packet: updates/review/2026-10-19/)
- [x] Natural environment kit (terrain, rocks, scatter, foliage-like procedural plants): `blender/kits/nature.py` v1, canyon + new meadow biome
- [ ] **[Doug]** Approve or send back `nature_kit` v1 (packet: updates/review/2026-10-19/)
- [x] Interior kit (rooms, furniture blocks, practical lights): `blender/kits/interior.py` v1, new `interior` environment
- [ ] **[Doug]** Approve or send back `interior_kit` v1 (packet: updates/review/2026-10-20/)
- [x] Hero asset generators (vehicles, machines, sculptural pieces) beyond primitives: `blender/kits/heroes.py` v1 (vehicle, robot_arm, torus_knot, crystal_cluster, twisted_column)
- [ ] **[Doug]** Approve or send back `hero_kit` v1 (packet: updates/review/2026-10-20/)
- [ ] Stylized character generator with rig, plus procedural walk/idle cycles
- [ ] FX: Mantaflow smoke/fire and liquid sims, rigid-body destruction
- [ ] Shader library expansion (wear, dirt, layered materials), photoreal + toon variants
- [ ] Real toon look: ramp lighting, Freestyle line pass as an extra layer
- [ ] **[Doug]** Approve each kit from its turntable/contact sheet (art direction notes go into the next night's work)

## Phase 3: LTX-ready outputs
- [x] Same scene rendered in both styles (`run_batch --style-pairs`; depth passes match exactly)
- [x] Captions from the spec (scene, camera move, lens, lighting, style) + review queue for human edits (`captions.py`, `review captions`; edits logged as provenance notes)
- [x] Export step: per-pass MP4 videos, /32 resolution, 8n+1 frames, IC-LoRA pair manifests (`export.py`)
- [x] Pair sets: depth/normal/segmentation/albedo → final, beauty → finished comp, light group → relit
- [x] toon ↔ photoreal pair manifests
- [x] Storage trims: native /32 resolutions (1920×1088); RGB-only light layers not possible in Blender 5.2 (documented)
- [ ] **[Doug]** Run `build_comp.py` in real Nuke on one shot; send back `comp/*_comp.json` warnings

## Phase 4: benchmark and generate
- [ ] **[Doug]** Render machine details: OS, GPU model, storage path (Nuke: 1 license, so comps run one at a time; time zone: Central; renders run on Doug's local GPU via a local Claude session or a scheduled run_batch)
- [x] Machine-specific nightly scheduler: `scripts/windows/nightly.bat` + `register_nightly.ps1` (Task Scheduler, wake to run; untested on Windows)
- [ ] 20-clip benchmark: real s/frame, GB/frame, look review
- [ ] **[Doug]** Approve the benchmark look → start the 500-clip pilot run (nightly until done)
- [ ] Morning progress: clips done, QA failures, ETA

## Phase 5: proof of benefit
- [ ] LTX IC-LoRA training configs for 2–3 pair sets
- [ ] **[Doug]** Train on LTX trainer (your GPUs), before/after eval clips
- [ ] Pilot package: sample set, manifest, datasheet, provenance report, pitch sheet

## Later pilots
- [ ] Keying module (plate / FG+alpha with spill / clean plate, screen light group for despill)
- [ ] Lens flare renderer (lens prescriptions, ghosts, diffraction starburst, video-consistent)
