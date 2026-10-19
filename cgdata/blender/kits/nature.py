"""Procedural natural-environment kit: terrain, rocks, trees, shrubs, grass.

Biomes:
    canyon   rugged terrain, strata rock formations, sparse shrubs
    meadow   rolling terrain, grass tufts, tree ring, scattered rocks

Terrain height comes from an analytic noise function that is flattened
around the hero, so every scattered piece is placed exactly on the ground
without ray casts. Like the city kit, everything is bmesh geometry with
procedural materials: fully owned and reproducible from the seed.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector, noise

from kits.city import Mesh

KIT = "nature_kit"
VERSION = 1

FLAT_RADIUS = 10.0    # ground is flat (z=0) inside this radius...
BLEND_RADIUS = 18.0   # ...and reaches full terrain height here

BIOMES = {
    #           amplitude, feature size, rocks, trees, shrubs, grass tufts
    "canyon": dict(amp=7.0, size=28.0, rocks=26, trees=0, shrubs=30, grass=0),
    "meadow": dict(amp=2.5, size=40.0, rocks=10, trees=22, shrubs=24, grass=1400),
}


# Photoreal (h, s, v) ranges per surface; toon shots use the scene palette
# at a similar hue instead.
NATURE_HSV = {
    "grass_ground": ((0.17, 0.25), (0.45, 0.65), (0.18, 0.3)),
    "sand": ((0.06, 0.09), (0.35, 0.55), (0.45, 0.62)),
    "canyon_rock": ((0.03, 0.07), (0.45, 0.65), (0.35, 0.52)),
    "grey_rock": ((0.08, 0.12), (0.05, 0.12), (0.3, 0.42)),
    "foliage": ((0.2, 0.3), (0.5, 0.75), (0.16, 0.32)),
    "grass": ((0.16, 0.24), (0.45, 0.7), (0.25, 0.42)),
    "bark": ((0.06, 0.09), (0.3, 0.5), (0.12, 0.22)),
}


def tone(builder, rng, surface):
    lo_h, hi_h = NATURE_HSV[surface][0]
    if builder.style == "toon":
        return builder.color(rng, hue=rng.uniform(lo_h, hi_h))
    import colorsys
    h, s_, v = (rng.uniform(*r) for r in NATURE_HSV[surface])
    return (*colorsys.hsv_to_rgb(h, s_, v), 1.0)


class Terrain:
    def __init__(self, seed, amp, size):
        self.offset = Vector(((seed % 1009) * 3.1, (seed % 997) * 2.7, 0))
        self.amp, self.size = amp, size

    def height(self, x, y):
        r = math.hypot(x, y)
        t = min(max((r - FLAT_RADIUS) / (BLEND_RADIUS - FLAT_RADIUS), 0.0), 1.0)
        falloff = t * t * (3 - 2 * t)
        p = Vector((x / self.size, y / self.size, 0)) + self.offset
        h = noise.fractal(p, 0.5, 2.0, 5, noise_basis="PERLIN_ORIGINAL")
        return self.amp * h * falloff

    def mesh(self, half, cells):
        m = Mesh()
        step = 2 * half / cells
        rows = []
        for j in range(cells + 1):
            y = -half + j * step
            rows.append([m.bm.verts.new((x, y, self.height(x, y)))
                         for x in (-half + i * step for i in range(cells + 1))])
        for j in range(cells):
            for i in range(cells):
                f = m.bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
                f.smooth = True
                for loop in f.loops:
                    loop[m.uv].uv = (loop.vert.co.x, loop.vert.co.y)
        return m


# ------------------------------------------------------------------ pieces

def _icosphere(m, center, radius, mat, rng, rough=0.35, squash=(1, 1, 1), subdiv=2, flat_base=None):
    geom = bmesh.ops.create_icosphere(m.bm, subdivisions=subdiv, radius=radius)
    seed = Vector((rng.uniform(0, 100), rng.uniform(0, 100), rng.uniform(0, 100)))
    for v in geom["verts"]:
        d = v.co.normalized()
        bump = noise.fractal(d * 1.7 + seed, 0.6, 2.0, 4)
        v.co = Vector((v.co.x * squash[0], v.co.y * squash[1], v.co.z * squash[2])) * (1 + rough * bump)
        if flat_base is not None:
            v.co.z = max(v.co.z, flat_base)
        v.co += Vector(center)
    for f in {f for v in geom["verts"] for f in v.link_faces}:
        f.material_index = mat
        f.smooth = True


def _cone(m, a, b, r0, r1, mat, segments=8):
    """A tapered cylinder from point a to point b."""
    a, b = Vector(a), Vector(b)
    axis = b - a
    rot = axis.to_track_quat("Z", "Y").to_matrix().to_4x4()
    mtx = Matrix.Translation((a + b) / 2) @ rot
    geom = bmesh.ops.create_cone(m.bm, cap_ends=True, cap_tris=False, segments=segments,
                                 radius1=r0, radius2=r1, depth=axis.length, matrix=mtx)
    for f in {f for v in geom["verts"] for f in v.link_faces}:
        f.material_index = mat
        f.smooth = True


def rock(m, rng, base, size, mat, strata=False):
    if strata:
        # stacked, slightly offset slabs: layered sandstone
        z = 0.0
        for i in range(rng.randint(3, 6)):
            h = size * rng.uniform(0.25, 0.45)
            w = size * rng.uniform(0.7, 1.1) * (1 - i * 0.08)
            off = Vector((rng.uniform(-0.15, 0.15) * size, rng.uniform(-0.15, 0.15) * size, 0))
            _icosphere(m, Vector(base) + off + Vector((0, 0, z + h / 2)), 1.0, mat, rng, rough=0.3,
                       squash=(w, w * rng.uniform(0.7, 1.0), h / 2), subdiv=3)
            z += h * 0.85
    else:
        _icosphere(m, Vector(base) + Vector((0, 0, size * 0.25)), size, mat, rng, rough=0.4,
                   squash=(1, rng.uniform(0.6, 1), rng.uniform(0.45, 0.8)), subdiv=3, flat_base=-size * 0.3)


def tree(m, rng, base, height, bark, leaves):
    base = Vector(base)
    top = base + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), height))
    trunk_r = height * 0.035
    _cone(m, base, top, trunk_r, trunk_r * 0.35, bark)
    ends = [top]
    for i in range(rng.randint(4, 7)):
        t = rng.uniform(0.45, 0.85)
        start = base.lerp(top, t)
        ang = rng.uniform(0, math.tau)
        length = height * rng.uniform(0.25, 0.4) * (1.1 - t)
        end = start + Vector((math.cos(ang), math.sin(ang), rng.uniform(0.5, 1.0))).normalized() * length
        _cone(m, start, end, trunk_r * 0.45, trunk_r * 0.12, bark, 6)
        ends.append(end)
    for e in ends:
        for _ in range(rng.randint(2, 3)):
            c = e + Vector((rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), rng.uniform(-0.3, 0.5)))
            _icosphere(m, c, height * rng.uniform(0.1, 0.16), leaves, rng, rough=0.45, subdiv=2)


def shrub(m, rng, base, size, leaves):
    for _ in range(rng.randint(3, 6)):
        c = Vector(base) + Vector((rng.uniform(-0.5, 0.5) * size, rng.uniform(-0.5, 0.5) * size,
                                   size * rng.uniform(0.25, 0.5)))
        _icosphere(m, c, size * rng.uniform(0.3, 0.5), leaves, rng, rough=0.5, subdiv=2)


def grass_tuft(m, rng, base, height, mat):
    base = Vector(base)
    for _ in range(rng.randint(5, 9)):
        ang = rng.uniform(0, math.tau)
        lean = Vector((math.cos(ang), math.sin(ang), 0)) * rng.uniform(0.05, 0.35) * height
        side = Vector((-math.sin(ang), math.cos(ang), 0)) * 0.015
        h = height * rng.uniform(0.6, 1.0)
        root = base + Vector((rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), 0))
        verts = [m.bm.verts.new(root - side), m.bm.verts.new(root + side),
                 m.bm.verts.new(root + lean + Vector((0, 0, h)))]
        f = m.bm.faces.new(verts)
        f.material_index = mat
        for loop, uv in zip(f.loops, ((0, 0), (1, 0), (0.5, 1))):
            loop[m.uv].uv = uv


# ------------------------------------------------------------------- build

def build_nature(builder, rng, extent, density, biome):
    cfg = BIOMES[biome]
    col = builder.scene.collection
    terrain = Terrain(rng.randrange(1 << 20), cfg["amp"], cfg["size"])

    if biome == "canyon":
        ground_color, rock_color = tone(builder, rng, "sand"), tone(builder, rng, "canyon_rock")
    else:
        ground_color, rock_color = tone(builder, rng, "grass_ground"), tone(builder, rng, "grey_rock")
    leaf_color, bark_color = tone(builder, rng, "foliage"), tone(builder, rng, "bark")

    half = extent * 2
    ground = terrain.mesh(half, 160)
    obj = ground.to_object("terrain", [builder.material("ground", ground_color)], col)
    builder.add_mesh(obj, "ground", "ground", "ENV")

    from scene import CLEAR_RADIUS  # the camera's clear zone

    # Inside the clear zone, keep scatter off the camera's side of the hero
    # (widened by how far an orbit can swing), so nothing sits in front of the lens.
    cam = builder.spec["camera"]
    cam_az = math.radians(cam["azimuth_deg"])
    keep_out = math.radians(70 + (90 * cam["travel"] if cam["move"] == "orbit" else 0))

    def place(r_min, r_max):
        while True:
            ang = rng.uniform(0, math.tau)
            r = rng.uniform(r_min, r_max)
            off = abs((ang - cam_az + math.pi) % math.tau - math.pi)
            if r > CLEAR_RADIUS + 1 or off > keep_out:
                break
        x, y = math.cos(ang) * r, math.sin(ang) * r
        return Vector((x, y, terrain.height(x, y)))

    rocks = Mesh()
    for _ in range(int(cfg["rocks"] * density)):
        size = rng.uniform(1.5, 6.0) if biome == "canyon" else rng.uniform(0.4, 1.6)
        rock(rocks, rng, place(CLEAR_RADIUS + 3, extent), size, 0, strata=biome == "canyon")
    for _ in range(int(cfg["rocks"] * density * 1.5)):  # small rocks, may sit in the clear zone
        rock(rocks, rng, place(4.0, extent), rng.uniform(0.15, 0.5), 0)
    obj = rocks.to_object("rocks", [builder.material("rock", rock_color)], col)
    builder.add_mesh(obj, "environment", "rock", "ENV")

    flora = Mesh()
    for _ in range(int(cfg["trees"] * density)):
        tree(flora, rng, place(CLEAR_RADIUS + 2, extent), rng.uniform(5.0, 11.0), 0, 1)
    for _ in range(int(cfg["shrubs"] * density)):
        shrub(flora, rng, place(6.0, extent), rng.uniform(0.6, 1.6), 1)
    if len(flora.bm.verts):
        obj = flora.to_object("vegetation", [builder.material("bark", bark_color),
                                             builder.material("foliage", leaf_color)], col)
        builder.add_mesh(obj, "environment", "foliage", "ENV")
    else:
        flora.bm.free()

    if cfg["grass"]:
        grass = Mesh()
        grass_color = tone(builder, rng, "grass")
        for _ in range(int(cfg["grass"] * density)):
            p = place(3.0, min(extent, 40.0))
            grass_tuft(grass, rng, p, rng.uniform(0.25, 0.6), 0)
        obj = grass.to_object("grass", [builder.material("foliage", grass_color)], col)
        builder.add_mesh(obj, "environment", "foliage", "ENV")

    return {"kit": KIT, "version": VERSION, "biome": biome}
