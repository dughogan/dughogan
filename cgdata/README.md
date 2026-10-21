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

### Keying clips (green/blue screen)

`run_batch --environment greenscreen` (or `spec --environment greenscreen`)
renders clips on a procedural cyclorama stage instead of a location; their
ids are `KY_xxxxxx`, so seed ranges never collide with `CG_` clips, and the
stage is never drawn at random. The stage (`blender/kits/stage.py`) is a
green or blue screen with uneven lighting, optional tracking markers and
real floor shadows, sized from the placed camera so it fills every frame of
the move. Lighting is studio: area key and fill on the camera side and a rim
spot in front of the screen. There are no props, fog or FX on the stage.

Extra view layers give exact keying ground truth, written into the light EXR
as RGBA layers:

| Layer | What it is |
|---|---|
| `Combined` | the plate: subject in front of the screen, with spill |
| `Key_FG` | screen invisible to camera but still lighting the subject: foreground with spill |
| `Key_FG_nospill` | screen removed: the despilled foreground; **its alpha is the matte** (glass is fractional) |
| `Key_Clean` | subject removed: the clean plate |
| `Combined_screen` | light group: the screen's own emission and the spill it throws |

`Key_FG`'s alpha reads opaque through glass, because glass refracts the
camera-invisible screen behind it; use `Key_FG_nospill`'s alpha. Keying
layers render at full samples, so a keying clip costs about four renders
per frame. Export adds `key_plate`, `key_alpha`, `key_fg`, `key_fg_spill`,
`key_clean` and `key_shadow` videos, and the pair sets `key_alpha`,
`key_fg`, `key_clean`, `key_shadow` (each conditioned on the plate) and
`key_despill`. The shadow matte is `1 - plate/clean` outside the subject,
smoothed before the ratio.

### Lens flares

`run_batch --flares` (or `python -m cgdata.flares <shot dirs>`) adds a lens
flare layer to photoreal clips after rendering, as
`renders/<id>_flare.####.exr` plus `flare.json`. The render is not touched:

| Layer | What it is |
|---|---|
| `Flare` | the stray light the lens scatters: diffraction starburst, veiling halo, ghosts |
| `Sun` | the sun's own disc (the render has none; the sun lamp is the key light), when Blender's ray cast finds it unblocked from the lens |

The clean plate is `Combined + Sun` and the flared plate is
`Combined + Sun + Flare`. The lens is seeded per clip, and it is a
**parametric model, not a ray trace through a real lens prescription**:
- **Starburst:** the PSF of an n-blade aperture (rounded blades, dust),
  computed as |FFT(pupil)|² at seven wavelengths, so spike count follows
  the blade count and the spikes fringe spectrally. It is designed at
  1920 px width and resampled, so a lens looks the same at any resolution.
- **Ghosts:** aperture-shaped discs on the line through frame centre, with
  coating tints, rims and slight dispersion.

Sources are taken from the frame itself (everything above luminance 3)
plus the sun, so flares track their sources from frame to frame; a sun just
outside the frame still throws glare and ghosts in. Export adds
`flare_clean`, `flare_plate` and `flare_only` videos and the
`flare_removal` / `flare_addition` pair sets for clips whose flare is
visible. Cost: about 2 s per 1920×1088 frame on CPU.

### Pilot package

`python -m cgdata.package LIBRARY --out PILOT --samples 24 --with-exr 4`
assembles a buyer-ready folder: a stratified sample of curated clips (style
pairs kept together), filtered pair manifests, a generated DATASHEET.md, a
PITCH_DRAFT.md with the numbers filled in, each clip's ComfyAudit provenance
record and optional full-EXR samples.

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

Renders are sharp: depth of field is added in comp (ZDefocus) from clean
depth, like motion blur, using the focus distance and f-stop recorded per
frame in the camera track.

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
