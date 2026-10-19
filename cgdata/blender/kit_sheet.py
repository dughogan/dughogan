"""Render a review sheet for an asset kit: the evidence for an asset_approved decision.

    python cgdata/blender/kit_sheet.py --kit city --style photoreal --seed 1 --out sheets/city_photoreal.png
    blender -b --factory-startup -P cgdata/blender/kit_sheet.py -- --kit city --style toon --out ...

Lays out a row of kit pieces under a neutral sun and sky and renders one
3/4 still. Pass the PNG to `cgdata.review asset ... --evidence`.
"""

import argparse
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import passes  # noqa: E402
from kits import city, nature  # noqa: E402
from scene import Builder  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kit", choices=["city", "nature"], default="city")
    ap.add_argument("--style", choices=["photoreal", "toon"], default="photoreal")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=6)
    ap.add_argument("--resolution", type=int, nargs=2, default=[1600, 700])
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--device", choices=["CPU", "GPU"], default="CPU")
    ap.add_argument("--exposure", type=float, default=0.0, help="display exposure (stops)")
    ap.add_argument("--sun", type=float, default=2.2, help="sun strength")
    ap.add_argument("--sky", type=float, default=0.3, help="sky strength")
    ap.add_argument("--out", type=Path, required=True)
    return ap.parse_args(argv)


def _nature_lineup(b, rng, scene):
    """Trees, shrubs, strata and boulder rocks, and a grass patch, in a row."""
    m = city.Mesh()
    x = 0.0
    for h in (6.0, 9.0, 11.0):
        nature.tree(m, rng, (x, 0, 0), h, 0, 1)
        x += 7.0
    for size in (1.0, 1.6):
        nature.shrub(m, rng, (x, 0, 0), size, 1)
        x += 3.5
    nature.rock(m, rng, (x + 2, 0, 0), 3.0, 2, strata=True)
    x += 8.0
    nature.rock(m, rng, (x, 0, 0), 1.6, 2)
    x += 4.0
    for _ in range(120):
        nature.grass_tuft(m, rng, (x + rng.uniform(-2, 2), rng.uniform(-2, 2), 0), rng.uniform(0.3, 0.6), 3)
    x += 3.0
    mats = [b.material("bark", nature.tone(b, rng, "bark")),
            b.material("foliage", nature.tone(b, rng, "foliage")),
            b.material("rock", nature.tone(b, rng, "canyon_rock")),
            b.material("foliage", nature.tone(b, rng, "grass"))]
    b.add_mesh(m.to_object("nature_kit", mats, scene.collection), "environment", "foliage", "ENV")
    return x, 11.0


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = args.device
    scene.cycles.samples = args.samples
    scene.render.resolution_x, scene.render.resolution_y = args.resolution
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = args.exposure
    scene.render.image_settings.file_format = "PNG"

    spec = {"seed": args.seed, "style": args.style, "camera": {"azimuth_deg": 0}}
    b = Builder(spec)
    rng = random.Random(args.seed)

    x, tallest = 0.0, 0.0
    if args.kit == "nature":
        x, tallest = _nature_lineup(b, rng, scene)
    for i in range(args.count if args.kit == "city" else 0):
        w, d = rng.uniform(7, 10), rng.uniform(7, 10)
        floors = [3, 5, 8, 4, 10, 6, 2, 12][i % 8]
        m = city.Mesh()
        tallest = max(tallest, city.building(m, rng, (x + w / 2, 0), w, d, floors, 0.2))
        kind = ["brick", "painted", "concrete"][i % 3]
        mats = city.building_materials(b, rng, kind)
        b.add_mesh(m.to_object(f"kit_{i}", mats, scene.collection), "environment", kind, "ENV")
        x += w + 3.0
    ground = city.Mesh()
    ground.box((x / 2, 0, -0.05), (x + 60, 60, 0.1), 0)
    b.add_mesh(ground.to_object("ground", [b.material("concrete", (0.45, 0.44, 0.42, 1.0))],
                                scene.collection), "ground", "concrete", "ENV")

    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = args.sun
    sun.rotation_euler = (math.radians(50), 0, math.radians(35))  # from the camera's right
    scene.collection.objects.link(sun)
    b._world(40.0, math.radians(35), args.sky)

    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.lens = 35
    scene.collection.objects.link(cam)
    scene.camera = cam
    target = Vector((x / 2, 0, tallest * 0.45))
    cam.location = target + Vector((-x * 0.4, -x * 1.05, tallest * 0.25))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.out.resolve())
    bpy.ops.render.render(write_still=True)
    print(f"kit_sheet: wrote {args.out}")


if __name__ == "__main__":
    main()
