"""Build and render one dataset shot from a spec.

Runs either inside Blender or with the `bpy` Python module:
    blender -b --factory-startup -P cgdata/blender/build_shot.py -- --spec CG_000001.json --out LIBRARY/cg
    python cgdata/blender/build_shot.py --spec CG_000001.json --out LIBRARY/cg

Writes into <out>/<shot_id>/:
    renders/<shot_id>_light.####.exr  multilayer EXR, half: beauty, light passes, light groups, AOVs
    renders/<shot_id>_data.####.exr   multilayer EXR, float: depth, position, normals, vectors, crypto
    preview/<shot_id>.####.png        sRGB beauty preview
    scene/<shot_id>.blend        the scene, re-renderable
    spec.json                    the input recipe
    scene.json                   objects, materials, lights, camera track, passes
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

import passes  # noqa: E402
from scene import Builder  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", choices=["CPU", "GPU"], default="GPU")
    ap.add_argument("--no-render", action="store_true", help="build and save the .blend only")
    return ap.parse_args(argv)


def setup_device(scene, device):
    scene.cycles.device = "CPU"
    if device != "GPU":
        return "CPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == backend]
        if gpus:
            for d in prefs.devices:
                d.use = d.type == backend
            scene.cycles.device = "GPU"
            return backend
    print("build_shot: no GPU found, rendering on CPU")
    return "CPU"


def main():
    args = parse_args()
    spec = json.loads(args.spec.read_text())
    shot_dir = args.out / spec["shot_id"]
    (shot_dir / "renders").mkdir(parents=True, exist_ok=True)
    (shot_dir / "scene").mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    passes.configure(scene, spec)
    device = setup_device(scene, args.device)

    builder = Builder(spec)
    builder.build()

    render_dir = (shot_dir / "renders").resolve()
    written = passes.add_exr_outputs(scene, render_dir, spec["shot_id"])
    (shot_dir / "preview").mkdir(exist_ok=True)
    scene.render.filepath = str((shot_dir / "preview" / f"{spec['shot_id']}.").resolve()) + "####"
    blend_path = shot_dir / "scene" / f"{spec['shot_id']}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path.resolve()), compress=True)

    (shot_dir / "spec.json").write_text(json.dumps(spec, indent=2))
    scene_info = {
        "shot_id": spec["shot_id"],
        "blender_version": bpy.app.version_string,
        "render_device": device,
        "colorspace": "Linear Rec.709 (scene-linear, Blender working space)",
        "objects": builder.objects,
        "lights": builder.lights,
        "light_groups": passes.LIGHT_GROUPS,
        "uses": builder.uses,
        "hero": {"type": spec["hero"]["type"], "color": builder.hero_color,
                 "motion": getattr(builder, "hero_motion", None)},
        "skeleton": builder.skeleton_track(),
        "exr_layers": written,
        "camera": builder.camera_track(),
    }

    if not args.no_render:
        start = time.time()
        bpy.ops.render.render(animation=True)
        frames = spec["render"]["frame_end"] - spec["render"]["frame_start"] + 1
        scene_info["render_seconds_per_frame"] = round((time.time() - start) / frames, 2)

    (shot_dir / "scene.json").write_text(json.dumps(scene_info, indent=2))
    print(f"build_shot: wrote {shot_dir}")


if __name__ == "__main__":
    main()
