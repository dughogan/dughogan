# cgdata handoff

Start here. This hands the CG dataset pilot over from the cloud session
(claude.ai/code `session_0134GSACVHFG3m3x9hBnc23F`, 2026-10-18) to Doug's
workstation. Read this, then `ROADMAP.md`, then `README.md`.

## 1. What this is

Dugco is building licensable AI-training data: procedurally generated CG
shots (photoreal and toon) with every render pass, the `.blend` and `.nk`
files, and a finished Nuke comp per shot. All of it is owned by Dugco, which
has written clearance from ComfyUI for outside work. Keep that letter with
the chain-of-title records.

**First buyer:** LTX (Lightricks). The goal is general VFX-quality
improvement: new or better IC-LoRAs now, and extra training data for the
LTX 2.5 base model later.

**The pilot:** 500 clips that measurably improve an LTX IC-LoRA. 500 clips
won't move a flagship base model; base-model data is the follow-on 10,000+
clip set.

## 2. Current state (branch `cg-dataset-pipeline`)

| Piece | File | Status |
|---|---|---|
| Seeded shot specs | `spec.py` | Tested |
| Scene builder (env, hero, props, lights, camera) | `blender/scene.py` | Tested; **placeholder art** (primitives) |
| Materials, photoreal + toon, with material AOVs | `blender/materials.py` | Tested; toon look is basic |
| Passes, light groups, EXR outputs | `blender/passes.py` | Tested in Blender 5.2.2 (45 layers) |
| Render entry point | `blender/build_shot.py` | Tested on CPU; **GPU path untested** |
| QA + `meta.json` | `qa.py` | Tested; light and light-group rebuilds pass at ~0.03% |
| Nuke finishing comp | `nuke/build_comp.py`, `comp_params.py` | **Not yet run in real Nuke**: dry-run against an API stub only |
| Manifest | `catalog.py` | Tested |
| Batch runner with overnight stop | `run_batch.py` | Tested (`--stop-at` resumes the next night) |

Decisions already made:
- **Approval gates** (confirmed by Doug 2026-10-18): asset approved, look
  locked, shot curated, comp finished. These are the human-authorship record.
- **Clip length:** 97 frames at 24 fps, because LTX training expects 8n+1
  frames. Export must also make resolutions divisible by 32.
- **Precision split:** color passes are half-float and data passes
  (depth, position, normals, vectors, Cryptomatte) are full float, in two
  EXRs per frame.
- **No denoising on Combined**, so the passes add up to it exactly. The
  denoising data passes are stored for buyers who want to denoise.
- **Rights:** `rights.owner = "Dugco"` in every `meta.json`.

## 3. Set up the workstation (Windows, RTX PRO 6000)

1. Install **Blender 5.2 LTS**. The code targets the 5.x API and won't run on
   4.x, because the compositor and File Output APIs changed.
2. Clone the repo and check out the branch:
   ```bat
   git clone https://github.com/dughogan/dughogan
   cd dughogan
   git checkout cg-dataset-pipeline
   py -3.13 -m venv .venv
   .venv\Scripts\activate
   pip install -r cgdata\requirements.txt
   ```
3. Choose a library location on fast storage with **7–12 TB free** for the
   pilot. The examples below use `D:\cgdata\LIBRARY`.

## 4. First-run checks (in order)

**a. A GPU draft render.** This should take seconds per frame, not minutes:
```bat
python -m cgdata.spec --count 1 --seed 1 --quality draft --out D:\cgdata\specs
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup -P cgdata\blender\build_shot.py -- --spec D:\cgdata\specs\CG_000001.json --out D:\cgdata\LIBRARY\cg --device GPU
python -m cgdata.qa D:\cgdata\LIBRARY\cg\CG_000001
```
Check `scene.json` for `"render_device": "OPTIX"`; if it says CPU, the GPU
wasn't picked up. Open `qa\CG_000001_passes.png`. QA must print PASS.

**b. Nuke, which has never been run for real.** Use your one license:
```bat
"C:\Program Files\Nuke16.0vX\Nuke16.0.exe" -t cgdata\nuke\build_comp.py D:\cgdata\LIBRARY\cg\CG_000001
```
Then:
- Read `comp\CG_000001_comp.json`. Its `warnings` list any knob names that
  don't exist in your Nuke version; ZDefocus2 and Grain2 are the likely ones.
  Fix those in `build_comp.py`.
- Open `comp\CG_000001_comp.nk` and check that the light-group rebuild
  matches Combined.
- **Check the motion-vector direction:** a moving shot should blur along
  its motion. If it's backwards, swap the forward/backward mapping in
  `build_comp.py`.

**c. A 20-clip benchmark** at pilot quality. This gives the real seconds per
frame and GB per frame for the schedule:
```bat
python -m cgdata.run_batch --count 20 --seed 1 --quality pilot --library D:\cgdata\LIBRARY --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --nuke "C:\Program Files\Nuke16.0vX\Nuke16.0.exe"
python -m cgdata.catalog D:\cgdata\LIBRARY\cg --out D:\cgdata\LIBRARY\catalog
```

## 5. Nightly render, 10pm–7am Central

Ready-made: `cgdata\scripts\windows\nightly.bat` (edit the paths at the top)
and `register_nightly.ps1` (run once, elevated; wakes the machine at 22:00).
The manual version below is equivalent.

`run_batch` is resumable: each night it skips finished shots and stops
starting new ones at `--stop-at`. Save this as `D:\cgdata\nightly.bat`:
```bat
@echo off
cd /d C:\path\to\dughogan
call .venv\Scripts\activate
python -m cgdata.run_batch --count 500 --seed 1 --quality pilot --library D:\cgdata\LIBRARY ^
  --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" ^
  --nuke "C:\Program Files\Nuke16.0vX\Nuke16.0.exe" --stop-at 07:00 >> D:\cgdata\LIBRARY\batch.log 2>&1
```
Register it once:
```bat
schtasks /Create /TN "cgdata nightly" /SC DAILY /ST 22:00 /TR "D:\cgdata\nightly.bat"
```
In Task Scheduler, open the task properties and set it to **wake the computer to run it**. Also make
sure Windows doesn't sleep overnight. Nuke uses the one license during the
batch, so you can't open Nuke yourself while it's running.

Only start the 500-clip run after the benchmark look has been approved; that
approval is a gate. A shot that fails QA is listed in `batch.log` and stays
in the library with `qa.passed = false`.

## 6. Blender 5.x findings (details in README.md)

- Direct multilayer EXR render output saves **only Combined**; passes go
  through compositor File Output nodes instead.
- EXRs are **multi-part** (one part per layer); readers must walk every part.
- There's no Composite node; the compositor group output drives the
  render output. `compositor_device = "CPU"` avoids needing a GPU display
  context.
- A File Output `VECTOR` item drops the 4th component, so Vector is written
  as RGBA. There are no separate SSS passes in Cycles (SSS is in Diffuse).
- The node was renamed to `ShaderNodeVolumePrincipled`.

## 7. What's next (full list in ROADMAP.md)

1. **Provenance (phase 1): done 2026-10-19** (`provenance.py`, `review.py`,
   tests). On your machine set `COMFYAUDIT_PATH=C:\ai\ComfyUI\custom_nodes`
   before `run_batch`. Original plan, for reference: review `dughogan/comfy_workflow_audit`.
   The cloud session cloned it but never reviewed it. Then write
   `cgdata/provenance.py` to send the four gate events in Comfy Audit's
   format, hash-chained and referenced from `meta.json`, plus a small
   approve/reject CLI. That repo has strict rules: standard library only,
   it must import as `comfyaudit`, and tests run with
   `python -m pytest -q --ignore=tests/test_agent.py`. Read its `CLAUDE.md`
   and `HANDOFF.md` first.
2. **Asset library (phase 2):** procedural geometry-node kits (city,
   natural, interior), hero assets, a stylized character with rig and
   cycles, FX sims, a larger shader library and a real toon look. Each kit
   goes through the "asset approved" gate. This is the main bottleneck,
   about 3–4 weeks.
3. **LTX outputs (phase 3):**
   - render each scene in both styles
   - write captions from the spec, with human edits on a subset
   - export per-pass videos at /32 resolution and 8n+1 frames
   - build IC-LoRA pair manifests: depth/normal/segmentation → final,
     beauty → finished comp, light group → relit, toon ↔ photoreal
4. **Benchmark and render (phase 4):** sections 4c and 5 above.
5. **Proof of benefit (phase 5):** train an LTX IC-LoRA on the pilot data
   and show before/after results. Then build the pilot package: samples,
   manifest, datasheet, provenance report and pitch sheet.

**Later pilots:**
- a keying module: **v1 built 2026-10-21** (`blender/kits/stage.py`,
  `run_batch --environment greenscreen`, clip ids `KY_*`; see README
  "Keying clips"). Waiting on your look review.
- a lens flare renderer: **v1 built 2026-10-21** (`flares.py`,
  `run_batch --flares`; see README "Lens flares"). Parametric lens model;
  ray tracing real lens prescriptions would be v2. Waiting on your look
  review.

Estimated time to a pilot with proof of benefit: **6–8 weeks.**

## 8. Business notes from the planning conversation

These are estimates, not quotes.
- **LTX, exclusive, full CG package:** about $700K–$1M. Open around
  $1–1.5M.
- **Non-exclusive:** about $150–300K per buyer.
- **Prefer narrow exclusivity:** time-limited (12 months) or field-of-use
  (video generation only).
- **Other buyers for the same data:**
  - inverse rendering and relighting: NVIDIA research/Cosmos, Beeble,
    Netflix's Eyeline, Foundry, Autodesk Flow Studio
  - video models that emphasize licensed data: Moonvalley, Adobe Firefly,
    Runway, Luma
  - large Chinese labs: ByteDance, Alibaba, Tencent, Kuaishou (needs careful
    legal review)
  - brokers: Protege, Human Native, Defined.ai
- **Before pitching:**
  - Don't use anything confidential from the LTX retainer when approaching
    other buyers.
  - Tell LTX up front that you plan non-exclusive or out-of-field licensing.
  - Have an IP lawyer review the term sheet and the human-authorship
    approach. Copyright needs real human creative control, not a count of
    clicks; human selection and arrangement of the dataset is the strongest
    claim.

## 9. Open items for Doug

- [ ] Run the checks in section 4 and send back the Nuke warnings and benchmark numbers.
- [ ] Storage location for LIBRARY.
- [ ] Decide what happens to the **cloud scheduled tasks**, which still fire
  into the cloud session: a nightly build at 10:03pm CT
  (`trig_019uKiZendsLVXaW1ijjzegV`) and a morning update at 6:50am CT
  (`trig_012YCAAj9ZrLVkWCjWszjFe1`). Keep them so the cloud keeps building
  phases 1–3, or delete them at claude.ai/code under scheduled tasks if
  all work moves local.
- [ ] To bring the planning conversation onto this machine, run
  `claude --teleport session_0134GSACVHFG3m3x9hBnc23F` from a clean
  checkout of this repo, signed in with the same claude.ai account.
