# cgdata: procedural CG paired-data pipeline

> New here? Start with [HANDOFF.md](HANDOFF.md), then [ROADMAP.md](ROADMAP.md).

Generates fully owned, procedurally built CG shots in Blender/Cycles with every
render pass, light groups and material AOVs. Each shot gets a finishing comp in
Nuke, automated QA and a catalog record, so the output is ready for
AI-training data licensing.

```
spec (JSON, seeded) ─► Blender/Cycles (headless) ─► QA + meta.json ─► Nuke finishing comp ─► manifest.parquet
```

## Quick start

```bash
pip install -r cgdata/requirements.txt          # plus bpy==5.2.2, or use a Blender install

# one test shot, CPU, low quality
python -m cgdata.spec --count 1 --seed 1 --quality draft --out specs/
python cgdata/blender/build_shot.py --spec specs/CG_000001.json --out LIBRARY/cg --device CPU
nuke -t cgdata/nuke/build_comp.py LIBRARY/cg/CG_000001
python -m cgdata.qa LIBRARY/cg/CG_000001

# a batch, end to end (resumable; split across machines by --seed ranges)
python -m cgdata.run_batch --count 500 --seed 1 --quality pilot \
    --library LIBRARY --blender /opt/blender/blender --nuke /opt/Nuke16.0/Nuke16.0
```

Quality presets (`cgdata/spec.py`): `draft` 480×270/16spp/3f, `preview`
960×540/64spp/25f, `pilot` 1920×1080/512spp/97f, `pilot_4k`.

## Per-shot output

```
LIBRARY/cg/CG_000001/
├── spec.json                         seeded recipe: rebuilds the shot exactly
├── scene.json                        objects, materials, lights, per-frame camera
├── meta.json                         dataset record: specs, passes, QA, comp params, rights, checksums
├── scene/CG_000001.blend             re-renderable scene (procedural, nothing to pack)
├── renders/CG_000001_light.####.exr  half float  — beauty, light passes, light groups, material AOVs
├── renders/CG_000001_data.####.exr   full float  — depth, position, normal, vector, UV, IDs, Cryptomatte
├── preview/CG_000001.####.png        sRGB beauty preview
├── qa/CG_000001_passes.png           pass contact sheet (middle frame)
├── comp/CG_000001_comp.nk            generated Nuke finishing script (+ _comp.json params)
└── final/CG_000001_final.####.exr    finished comp (+ .png)
```

### Export for LTX training

`python -m cgdata.export LIBRARY` writes per-clip H.264 videos (target,
beauty, depth, camera-space normals, segmentation, albedo, each light group)
and IC-LoRA pair manifests (`export/pairs/*.jsonl`: caption, media_path,
conditioning_path). Only clips that passed QA and were kept at the
shot_curated gate are exported. Uses system ffmpeg, else `imageio-ffmpeg`.

### Passes (45 layers, verified in Blender 5.2)

| Group | Layers |
|---|---|
| Beauty | Combined |
| Light decomposition | DiffDir/Ind/Col, GlossDir/Ind/Col, TransDir/Ind/Col, VolumeDir/Ind, Emit, Env, AO |
| Light groups | Combined_key, _fill, _rim, _practical, _env |
| Material AOVs | base_color, roughness, metallic |
| Geometry | Depth, Mist, Position, Normal, UV |
| Motion | Vector (4ch: to-previous xy, to-next xy, pixels) |
| IDs | IndexOB, IndexMA, CryptoObject/Material/Asset 00–02 (+ manifests in header) |

Geometric passes (depth, mist, position, normal, vector, UV, IDs,
Cryptomatte) come from a second view layer, "Data", that excludes the
atmosphere collection: inside fog most camera samples scatter before
reaching a surface, which turned depth into noise. The beauty layer keeps the
volumetric light.
| Denoising data | Albedo, SpecAlbedo, Normal, Roughness, Depth |

Combined is rendered **without denoising**, so passes sum to it exactly. QA
checks both rebuilds on every frame:

```
Combined = (DiffDir+DiffInd)·DiffCol + (GlossDir+GlossInd)·GlossCol
         + (TransDir+TransInd)·TransCol + VolumeDir + VolumeInd + Emit + Env
Combined = Σ Combined_<lightgroup>
```

Test renders pass both at ~0.02–0.03% mean error (half-float rounding).

## Provenance (ComfyAudit)

Every clip, asset kit and look gets a ComfyAudit shot history
(`provenance.py`): hash-chained, signed and ledger-witnessed when
`COMFYAUDIT_HISTORY_KEY` / `COMFYAUDIT_HISTORY_LEDGER` are set. Render and comp
are machine entries that credit nobody. The four approval gates (asset
approved, look locked, shot curated, comp finished) are a named person's
decision, and each needs a note saying why. `run_batch` records the machine
steps automatically and refuses to start if ComfyAudit isn't importable (set
`COMFYAUDIT_PATH` to the folder containing `comfyaudit`, e.g.
`C:\ai\ComfyUI\custom_nodes`).

```bash
python -m cgdata.review shots LIBRARY --gate shot_curated --as "Doug Hogan"   # interactive curation
python -m cgdata.review asset LIBRARY city_kit_v1 --approve --note "..." --as "Doug Hogan"
python -m cgdata.review captions LIBRARY --as "Doug Hogan"                    # caption edits (logged)
python -m cgdata.review status LIBRARY
python -m cgdata.review record LIBRARY/cg/CG_000001 --out CG_000001_provenance.html
```

Tests: `COMFYAUDIT_PATH=... python -m pytest -q cgdata/tests`

## Comp (Nuke)

`build_comp.py` rebuilds the beauty from light groups (each with its own
gain), then applies depth haze, ZDefocus, VectorBlur, Glow, chromatic
aberration, vignette, a grade and grain. Toon shots get a cleaner finish:
no grain, no CA, lighter glow. Parameters are seeded per shot
(`cgdata/comp_params.py`) and recorded in `meta.json`. Layer names are
found at runtime from the Read nodes, and missing knobs are reported as
warnings instead of crashing, so the script tolerates differences between
Nuke versions.

**Status:** dry-run tested against a stub of the Nuke API using real EXRs.
The graph wiring and layer lookups are verified; it has not yet been run in
real Nuke. On the first real run, check `comp/*_comp.json` for knob
warnings (ZDefocus2/Grain2 knob names vary by version) and the Vector sign
convention for VectorBlur. Rendering needs a commercial Nuke license on
each render node; Nuke Non-commercial can't be used.

## Blender 5.x notes (learned the hard way)

- Direct render output of a multilayer EXR saves **only Combined** in 5.2.
  Passes are written through compositor File Output nodes instead.
- Multilayer EXRs are **multi-part** (one part per layer). Readers must walk
  every part.
- There is no Composite node; the compositor node group's Group Output
  drives the render output. Set `compositor_device = "CPU"` on headless nodes
  without EGL.
- Cycles has no separate subsurface passes (SSS is in Diffuse), and Shadow is
  EEVEE-only.
- A File Output `VECTOR` item defaults to 3 components; Vector is written with
  `vector_socket_dimensions = 4` (channels X, Y, Z, W).
- `color_mode = "RGB"` is ignored on multilayer File Outputs (node-wide and
  per item), so light layers carry an always-1.0 alpha.
- `ShaderNodeVolumePrincipled` (renamed from `ShaderNodePrincipledVolume`).

## Current limits / next steps

- **Assets are placeholder primitives.** The environments (city block,
  canyon), heroes, props and materials prove the pipeline but aren't
  dataset-quality art. Next: modular procedural kits (geometry nodes),
  stylized characters with rigs, owned mocap, FX sims, a larger shader
  library and a real toon look (outlines via Freestyle as an extra pass).
- Storage: draft frames measured about 15 MB at 480×270, which projects to
  roughly 150–250 MB per 1080p frame. Clean high-sample frames compress
  better. Light layers carry an unused alpha (~25% of their size) that
  Blender 5.2 won't drop; stripping it would mean rewriting every EXR.
- `rights.owner` in `meta.json` is Dugco (cleared with ComfyUI for outside work).
