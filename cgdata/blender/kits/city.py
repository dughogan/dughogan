"""Modular procedural city kit: buildings, plaza, streets and street dressing.

Layout: a paved plaza around the hero (kept clear for the camera), a ring
road, then city blocks of buildings facing in. Buildings are built facade by
facade with bmesh: wall panels around recessed windows (some lit), a
storefront ground floor with awnings, cornices, a parapet and rooftop units.
Every facade face gets meter-scale UVs, so brick and other UV-driven
materials tile at real-world size and the UV pass carries usable data.

Material slots per building: see SLOTS. Lit windows and lamp heads are
emissive and sit in the "practical" light group.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

KIT = "city_kit"
VERSION = 1

SLOTS = ["wall", "trim", "window", "window_lit", "roof", "awning"]
WALL, TRIM, WINDOW, WINDOW_LIT, ROOF, AWNING = range(len(SLOTS))

PLAZA_HALF = 20.0     # plaza spans -20..20 on both axes
STREET_WIDTH = 9.0    # curb to curb
SIDEWALK = 2.0
BLOCK = 24.0          # block size, sidewalk included
UP = Vector((0, 0, 1))


# ------------------------------------------------------------ mesh helpers

class Mesh:
    """bmesh with per-face material and UVs, and outward-facing quads."""

    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")

    def quad(self, pts, uvs, mat, facing):
        verts = [self.bm.verts.new(p) for p in pts]
        face = self.bm.faces.new(verts)
        face.material_index = mat
        face.normal_update()
        if face.normal.dot(facing) < 0:
            face.normal_flip()  # loops reverse; UVs follow their vertices below
        for loop in face.loops:
            loop[self.uv].uv = uvs[verts.index(loop.vert)]
        return face

    def box(self, center, size, mat, rot=0.0):
        """Axis box (optionally rotated about Z), UVs in meters per side."""
        c = Vector(center)
        sx, sy, sz = (s / 2 for s in size)
        R = Matrix.Rotation(rot, 3, "Z")
        corners = {(i, j, k): c + R @ Vector((i * sx, j * sy, k * sz))
                   for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)}
        sides = [  # (normal, four corners as (i,j,k), uv extents)
            ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)], (2 * sx, 2 * sz)),
            ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)], (2 * sy, 2 * sz)),
            ((0, 1, 0), [(1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)], (2 * sx, 2 * sz)),
            ((-1, 0, 0), [(-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)], (2 * sy, 2 * sz)),
            ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)], (2 * sx, 2 * sy)),
            ((0, 0, -1), [(-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)], (2 * sx, 2 * sy)),
        ]
        for n, keys, (w, h) in sides:
            uvs = [(0, 0), (w, 0), (w, h), (0, h)]
            self.quad([corners[k] for k in keys], uvs, mat, R @ Vector(n))

    def cylinder(self, base, radius, height, mat, segments=12):
        geom = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segments,
                                     radius1=radius, radius2=radius, depth=height,
                                     matrix=Matrix.Translation(Vector(base) + Vector((0, 0, height / 2))))
        for v in geom["verts"]:
            for f in v.link_faces:
                f.material_index = mat

    def to_object(self, name, materials, collection):
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for m in materials:
            mesh.materials.append(m)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        return obj


# ---------------------------------------------------------------- facades

def _facade(m, p0, U, N, width, height, floors, ground_h, floor_h, rng, lit_fraction, storefront):
    """One side of a building: a grid of wall panels around recessed windows."""
    bays = max(1, round(width / rng.choice([2.4, 3.0, 3.6])))
    bay_w = width / bays
    depth = 0.18

    def P(u, v, d=0.0):
        return p0 + U * u + UP * v - N * d

    rows = [(0.0, ground_h, True)] + [(ground_h + i * floor_h, ground_h + (i + 1) * floor_h, False)
                                      for i in range(floors - 1)]
    for v0, v1, ground in rows:
        for b in range(bays):
            u0, u1 = b * bay_w, (b + 1) * bay_w
            if ground and storefront:
                mx, sill, head = 0.15, 0.35, 0.7
            else:
                mx, sill, head = bay_w * rng.uniform(0.18, 0.28), 0.9, 0.45
            wu0, wu1, wv0, wv1 = u0 + mx, u1 - mx, v0 + sill, v1 - head
            # wall panels around the opening
            for a0, a1, b0, b1 in ((u0, wu0, v0, v1), (wu1, u1, v0, v1),
                                   (wu0, wu1, v0, wv0), (wu0, wu1, wv1, v1)):
                m.quad([P(a0, b0), P(a1, b0), P(a1, b1), P(a0, b1)],
                       [(a0, b0), (a1, b0), (a1, b1), (a0, b1)], WALL, N)
            # reveal: sill, head, jambs
            for pts, facing in (
                ([P(wu0, wv0), P(wu1, wv0), P(wu1, wv0, depth), P(wu0, wv0, depth)], UP),
                ([P(wu0, wv1, depth), P(wu1, wv1, depth), P(wu1, wv1), P(wu0, wv1)], -UP),
                ([P(wu0, wv0, depth), P(wu0, wv1, depth), P(wu0, wv1), P(wu0, wv0)], U),
                ([P(wu1, wv0), P(wu1, wv1), P(wu1, wv1, depth), P(wu1, wv0, depth)], -U),
            ):
                m.quad(pts, [(0, 0), (1, 0), (1, depth), (0, depth)], TRIM, facing)
            lit = rng.random() < lit_fraction
            m.quad([P(wu0, wv0, depth), P(wu1, wv0, depth), P(wu1, wv1, depth), P(wu0, wv1, depth)],
                   [(wu0, wv0), (wu1, wv0), (wu1, wv1), (wu0, wv1)],
                   WINDOW_LIT if lit else WINDOW, N)
            if ground and storefront and rng.random() < 0.5:
                # awning over the storefront bay
                c = P((u0 + u1) / 2, v1 - 0.25) + N * 0.55
                rot = math.atan2(U.y, U.x)
                m.box(c, (bay_w * 0.9, 1.1, 0.08), AWNING, rot)


def building(m, rng, center, w, d, floors, lit_fraction, storefront=True):
    """A rectangular building centered at `center` (ground level)."""
    cx, cy = center
    ground_h = rng.uniform(3.6, 4.6) if storefront else rng.uniform(3.0, 3.4)
    floor_h = rng.uniform(3.0, 3.4)
    height = ground_h + floor_h * (floors - 1)
    hw, hd = w / 2, d / 2
    base = Vector((cx, cy, 0))
    sides = [  # (corner p0, U, N, width)
        (Vector((-hw, -hd, 0)), Vector((1, 0, 0)), Vector((0, -1, 0)), w),
        (Vector((hw, -hd, 0)), Vector((0, 1, 0)), Vector((1, 0, 0)), d),
        (Vector((hw, hd, 0)), Vector((-1, 0, 0)), Vector((0, 1, 0)), w),
        (Vector((-hw, hd, 0)), Vector((0, -1, 0)), Vector((-1, 0, 0)), d),
    ]
    for p0, U, N, width in sides:
        _facade(m, base + p0, U, N, width, height, floors, ground_h, floor_h, rng,
                lit_fraction, storefront)
    # roof slab, cornices every few floors, parapet
    m.box(base + Vector((0, 0, height - 0.05)), (w, d, 0.1), ROOF)
    every = rng.choice([1, 2, 3, 99])
    for i in range(1, floors):
        if i % every == 0:
            z = ground_h + (i - 1) * floor_h
            m.box(base + Vector((0, 0, z)), (w + 0.3, d + 0.3, 0.18), TRIM)
    m.box(base + Vector((0, 0, ground_h)), (w + 0.4, d + 0.4, 0.3), TRIM)
    for sx, sy, lx, ly in ((0, -hd, w, 0.25), (0, hd, w, 0.25), (-hw, 0, 0.25, d), (hw, 0, 0.25, d)):
        m.box(base + Vector((sx, sy, height + 0.45)), (lx, ly, 0.9), TRIM)
    # rooftop units
    for _ in range(rng.randint(0, 4)):
        s = rng.uniform(0.8, 2.2)
        p = base + Vector((rng.uniform(-hw + s, hw - s), rng.uniform(-hd + s, hd - s), height + s / 3))
        m.box(p, (s, s * rng.uniform(0.6, 1.2), s * 0.66), ROOF, rng.uniform(0, 0.2))
    if rng.random() < 0.3:  # water tower
        p = base + Vector((rng.uniform(-hw / 2, hw / 2), rng.uniform(-hd / 2, hd / 2), height))
        for ox, oy in ((-0.8, -0.8), (0.8, -0.8), (0.8, 0.8), (-0.8, 0.8)):
            m.cylinder(p + Vector((ox, oy, 0)), 0.08, 2.0, TRIM, 6)
        m.cylinder(p + Vector((0, 0, 2.0)), 1.4, 2.6, ROOF, 16)
    return height


# ---------------------------------------------------------------- dressing

def lamp_post(m, base, facing_rot):
    b = Vector(base)
    m.cylinder(b, 0.08, 4.6, 1)  # pole, trim slot
    arm_dir = Matrix.Rotation(facing_rot, 3, "Z") @ Vector((1, 0, 0))
    m.box(b + Vector((0, 0, 4.55)) + arm_dir * 0.5, (1.0, 0.08, 0.08), 1, facing_rot)
    head = b + Vector((0, 0, 4.45)) + arm_dir * 1.0
    m.box(head, (0.45, 0.25, 0.12), 2, facing_rot)  # emissive slot
    return head - Vector((0, 0, 0.12))


def bench(m, base, rot):
    b = Vector(base)
    R = Matrix.Rotation(rot, 3, "Z")
    m.box(b + Vector((0, 0, 0.45)), (1.8, 0.45, 0.06), 0, rot)
    m.box(b + R @ Vector((0, 0.2, 0.75)), (1.8, 0.05, 0.4), 0, rot)
    for sx in (-0.75, 0.75):
        m.box(b + R @ Vector((sx, 0, 0.22)), (0.08, 0.4, 0.44), 1, rot)


# Facade colors (h, s, v ranges) by wall material, for the photoreal style.
# Toon shots keep the scene's saturated palette.
FACADE_HSV = {
    "brick": ((0.01, 0.06), (0.45, 0.7), (0.3, 0.5)),
    "painted": ((0.05, 0.6), (0.15, 0.4), (0.5, 0.8)),
    "concrete": ((0.06, 0.12), (0.03, 0.12), (0.45, 0.65)),
}


def facade_color(builder, rng, kind):
    if builder.style == "toon":
        return builder.color(rng)
    h, s_, v = (rng.uniform(*r) for r in FACADE_HSV[kind])
    import colorsys
    return (*colorsys.hsv_to_rgb(h, s_, v), 1.0)


def building_materials(builder, rng, kind, lit_color=(1.0, 0.8, 0.55, 1.0)):
    """Material slots (see SLOTS) for one building with `kind` walls."""
    return [builder.material(kind, facade_color(builder, rng, kind)),
            builder.material("concrete", (0.55, 0.53, 0.5, 1.0)),
            builder.material("window", (0.02, 0.025, 0.03, 1.0)),
            builder.material("window_lit", lit_color),
            builder.material("concrete", (0.3, 0.3, 0.32, 1.0)),
            builder.material("painted", builder.color(rng))]


def build_city(builder, rng, extent, density, lit_fraction):
    """Place the whole kit. `builder` is scene.Builder (materials, objects)."""
    col = builder.scene.collection
    lit_colors = [(1.0, 0.75, 0.45, 1.0), (1.0, 0.9, 0.75, 1.0), (0.7, 0.85, 1.0, 1.0)]

    def mats(wall_kind):
        return building_materials(builder, rng, wall_kind, rng.choice(lit_colors))

    # Plaza and sidewalks are at z=0 (where the hero and props stand); the
    # road surface sits a curb height below them.
    ground = Mesh()
    ground.box((0, 0, -0.2), (extent * 4, extent * 4, 0.1), 0)
    ground.box((0, 0, -0.075), (PLAZA_HALF * 2, PLAZA_HALF * 2, 0.15), 1)
    obj = ground.to_object("city_ground", [builder.material("asphalt", (0.09, 0.09, 0.1, 1.0)),
                                           builder.material("concrete", (0.5, 0.49, 0.47, 1.0))], col)
    builder.add_mesh(obj, "ground", "asphalt", "ENV")

    # lane markings on the ring road
    marks = Mesh()
    ring = PLAZA_HALF + STREET_WIDTH / 2
    for side in range(4):
        R = Matrix.Rotation(side * math.pi / 2, 3, "Z")
        for t in range(-int(ring), int(ring), 4):
            marks.box(R @ Vector((t + 1, -ring, -0.145)), (2.0, 0.15, 0.01), 0, side * math.pi / 2)
    obj = marks.to_object("lane_markings", [builder.material("painted", (0.85, 0.85, 0.8, 1.0))], col)
    builder.add_mesh(obj, "environment", "painted", "ENV")

    # blocks around the plaza, out to the environment extent
    first = PLAZA_HALF + STREET_WIDTH
    pitch = BLOCK + STREET_WIDTH
    count = 0
    starts = [first + i * pitch for i in range(max(1, int((extent - first) // pitch) + 1))]
    centers = [s + BLOCK / 2 for s in starts]
    axis = [-c for c in centers[::-1]] + [0.0] + centers
    for bx in axis:
        for by in axis:
            if bx == 0 and by == 0:
                continue
            if abs(bx) < first and abs(by) < first:
                continue
            # sidewalk slab with curb
            slab = Mesh()
            slab.box((bx, by, -0.075), (BLOCK, BLOCK, 0.15), 0)
            obj = slab.to_object(f"sidewalk_{count:03d}", [builder.material("concrete", (0.5, 0.49, 0.47, 1.0))], col)
            builder.add_mesh(obj, "environment", "concrete", "ENV")
            # 2x2 lots per block
            lot = (BLOCK - 2 * SIDEWALK) / 2
            for lx in (-0.5, 0.5):
                for ly in (-0.5, 0.5):
                    if rng.random() > density:
                        continue
                    w, d = lot * rng.uniform(0.82, 0.98), lot * rng.uniform(0.82, 0.98)
                    floors = rng.choice([2, 3, 4, 5, 6, 8, 10, 14])
                    m = Mesh()
                    building(m, rng, (bx + lx * lot, by + ly * lot), w, d, floors, lit_fraction)
                    kind = rng.choice(["brick", "brick", "painted", "concrete"])
                    obj = m.to_object(f"bldg_{count:03d}", mats(kind), col)
                    builder.add_mesh(obj, "environment", kind, "ENV")
                    builder.assign_practical(obj)
                    count += 1

    # dressing on the plaza edge: lamps (real lights), benches, bollards, bins
    dress = Mesh()
    lamp_heads = []
    edge = PLAZA_HALF - 0.6
    for side in range(4):
        rot = side * math.pi / 2
        R = Matrix.Rotation(rot, 3, "Z")
        for t in range(-16, 17, 8):
            pos = R @ Vector((t, -edge, 0.0))
            lamp_heads.append(lamp_post(dress, pos, rot + math.pi / 2))
            if rng.random() < 0.5:
                bench(dress, R @ Vector((t + 4, -edge + 1.2, 0.0)), rot)
            for k in range(rng.randint(0, 3)):
                dress.cylinder(R @ Vector((t + 2 + k, -edge - 0.3, 0.0)), 0.12, 0.9, 1, 10)
            if rng.random() < 0.3:
                dress.cylinder(R @ Vector((t - 3, -edge + 0.4, 0.0)), 0.3, 0.95, 0, 14)
    obj = dress.to_object("plaza_dressing", [builder.material("metal", (0.2, 0.22, 0.2, 1.0)),
                                             builder.material("painted", (0.15, 0.15, 0.15, 1.0)),
                                             builder.material("emissive", (1.0, 0.8, 0.55, 1.0))], col)
    builder.add_mesh(obj, "environment", "metal", "ENV")
    builder.assign_practical(obj)
    for i, head in enumerate(lamp_heads):
        if rng.random() < lit_fraction + 0.3:
            builder.point_light(f"street_lamp_{i:02d}", head, 120.0, (1.0, 0.8, 0.55))
    return {"kit": KIT, "version": VERSION, "buildings": count}
