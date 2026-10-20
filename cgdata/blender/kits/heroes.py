"""Procedural hero assets: vehicles, machines and sculptural pieces.

Each generator builds one multi-material object at the origin, resting on
z=0, from the shot's hero seed. Proportions are randomized within believable
ranges so no two heroes repeat. Material slots are per generator (see each
function); the builder supplies the materials.
"""

import math

import bmesh
from mathutils import Matrix, Vector

from kits.city import Mesh
from kits.nature import _cone, _icosphere

KIT = "hero_kit"
VERSION = 1


# --------------------------------------------------------------- vehicle

def vehicle(m, rng, scale=1.0):
    """A car. Slots: 0 paint, 1 glass, 2 rubber, 3 chrome, 4 headlight, 5 taillight."""
    s = scale
    L, W = rng.uniform(3.9, 4.8) * s, rng.uniform(1.75, 1.95) * s
    clearance, body_h = 0.18 * s, rng.uniform(0.55, 0.7) * s
    wheel_r = rng.uniform(0.32, 0.38) * s
    cabin_l, cabin_h = L * rng.uniform(0.42, 0.55), rng.uniform(0.42, 0.55) * s
    cabin_off = rng.uniform(-0.12, 0.05) * L

    z0 = clearance + wheel_r * 0.6
    m.box((0, 0, z0 + body_h / 2), (L, W, body_h), 0)                         # lower body
    m.box((L * 0.47, 0, z0 + body_h * 0.75), (L * 0.08, W * 0.98, body_h * 0.5), 0)   # nose taper
    # cabin: glass box with a painted roof and pillars
    cz = z0 + body_h + cabin_h / 2
    m.box((cabin_off, 0, cz), (cabin_l, W * 0.86, cabin_h), 1)
    m.box((cabin_off, 0, z0 + body_h + cabin_h + 0.025 * s), (cabin_l * 0.92, W * 0.84, 0.05 * s), 0)
    for px in (-0.5, 0.5):
        for py in (-1, 1):
            m.box((cabin_off + px * cabin_l * 0.96, py * W * 0.43, cz), (0.06 * s, 0.05 * s, cabin_h), 0)
    # wheels: tire + rim, front and back axles
    for ax in (-L * 0.33, L * 0.33):
        for side in (-1, 1):
            y = side * (W / 2 - 0.12 * s)
            rot = Matrix.Rotation(math.pi / 2, 4, "X")
            for r, depth, slot in ((wheel_r, 0.24 * s, 2), (wheel_r * 0.62, 0.26 * s, 3)):
                geom = bmesh.ops.create_cone(m.bm, cap_ends=True, cap_tris=False, segments=24,
                                             radius1=r, radius2=r, depth=depth,
                                             matrix=Matrix.Translation((ax, y, wheel_r)) @ rot)
                for f in {f for v in geom["verts"] for f in v.link_faces}:
                    f.material_index = slot
                    f.smooth = True
    # lights and bumpers
    for side in (-1, 1):
        m.box((L / 2 + 0.01, side * W * 0.36, z0 + body_h * 0.7), (0.04 * s, 0.3 * s, 0.1 * s), 4)
        m.box((-L / 2 - 0.01, side * W * 0.38, z0 + body_h * 0.72), (0.04 * s, 0.28 * s, 0.08 * s), 5)
    for x in (L / 2 + 0.03, -L / 2 - 0.03):
        m.box((x, 0, z0 + 0.08 * s), (0.08 * s, W * 0.96, 0.14 * s), 3)


# --------------------------------------------------------------- machine

def robot_arm(m, rng, scale=1.0):
    """An industrial robot arm on a plinth. Slots: 0 paint, 1 metal, 2 rubber, 3 status light."""
    s = scale * rng.uniform(0.9, 1.3)
    m.box((0, 0, 0.15 * s), (1.2 * s, 1.2 * s, 0.3 * s), 1)                     # plinth
    m.cylinder((0, 0, 0.3 * s), 0.42 * s, 0.35 * s, 0, 24)                    # turret
    shoulder = Vector((0, 0, 0.85 * s))
    _icosphere(m, shoulder, 0.26 * s, 1, rng, rough=0.0, subdiv=2)
    a1 = math.radians(rng.uniform(25, 70))
    yaw = rng.uniform(0, math.tau)
    d = Vector((math.cos(yaw), math.sin(yaw), 0))
    elbow = shoulder + (d * math.cos(a1) + Vector((0, 0, 1)) * math.sin(a1)) * 1.2 * s
    _cone(m, shoulder, elbow, 0.17 * s, 0.13 * s, 0, 16)
    _icosphere(m, elbow, 0.19 * s, 1, rng, rough=0.0, subdiv=2)
    a2 = math.radians(rng.uniform(-60, 10))
    wrist = elbow + (d * math.cos(a2) + Vector((0, 0, 1)) * math.sin(a2)) * 1.0 * s
    _cone(m, elbow, wrist, 0.12 * s, 0.09 * s, 0, 16)
    _icosphere(m, wrist, 0.11 * s, 1, rng, rough=0.0, subdiv=2)
    tip = wrist + (wrist - elbow).normalized() * 0.25 * s
    _cone(m, wrist, tip, 0.07 * s, 0.07 * s, 1, 12)
    for side in (-1, 1):  # gripper fingers
        off = Vector((-d.y, d.x, 0)) * side * 0.06 * s
        _cone(m, tip + off, tip + off + (tip - wrist).normalized() * 0.16 * s, 0.025 * s, 0.015 * s, 2, 6)
    m.box((0.45 * s, 0, 0.32 * s), (0.08 * s, 0.25 * s, 0.05 * s), 3)          # status light
    m.cylinder((0, 0, 0.3 * s), 0.44 * s, 0.03 * s, 2, 24)                    # rubber seal ring


# ------------------------------------------------------------- sculptural

def torus_knot(m, rng, scale=1.0, slot=0):
    """A (p, q) torus knot swept as a tube."""
    p, q = rng.choice([(2, 3), (3, 2), (2, 5), (3, 4)])
    R, r_tube = 1.0 * scale, rng.uniform(0.12, 0.2) * scale
    n, k = 360, 18
    pts = []
    for i in range(n):
        t = i / n * math.tau
        rr = math.cos(q * t) + 2.0
        pts.append(Vector((rr * math.cos(p * t), rr * math.sin(p * t), -math.sin(q * t))) * R * 0.45)
    rings = []
    normal = None
    for i in range(n):
        tangent = (pts[(i + 1) % n] - pts[i - 1]).normalized()
        if normal is None:
            normal = tangent.orthogonal().normalized()
        normal = (normal - tangent * normal.dot(tangent)).normalized()  # parallel transport
        binormal = tangent.cross(normal)
        rings.append([m.bm.verts.new(pts[i] + (normal * math.cos(a) + binormal * math.sin(a)) * r_tube)
                      for a in (j / k * math.tau for j in range(k))])
    for i in range(n):
        a, b = rings[i], rings[(i + 1) % n]
        for j in range(k):
            f = m.bm.faces.new((a[j], a[(j + 1) % k], b[(j + 1) % k], b[j]))
            f.material_index = slot
            f.smooth = True
    bmesh.ops.recalc_face_normals(m.bm, faces=m.bm.faces)


def crystal_cluster(m, rng, scale=1.0, slot=0, base_slot=1):
    """Faceted crystal points rising from a rock base."""
    _icosphere(m, (0, 0, 0.15 * scale), 0.6 * scale, base_slot, rng, rough=0.4,
               squash=(1.2, 1.0, 0.45), subdiv=2, flat_base=-0.1 * scale)
    for _ in range(rng.randint(6, 11)):
        tilt = rng.uniform(0, 0.6)
        ang = rng.uniform(0, math.tau)
        base = Vector((math.cos(ang), math.sin(ang), 0)) * rng.uniform(0, 0.35) * scale + Vector((0, 0, 0.2 * scale))
        axis = Vector((math.cos(ang) * tilt, math.sin(ang) * tilt, 1)).normalized()
        h = rng.uniform(0.6, 1.8) * scale
        r = rng.uniform(0.09, 0.2) * scale
        mid = base + axis * h * 0.8
        _cone(m, base, mid, r, r, slot, 6)
        _cone(m, mid, base + axis * h, r, 0.001, slot, 6)
    for f in m.bm.faces:
        if f.material_index == slot:
            f.smooth = False  # crystals are faceted


def twisted_column(m, rng, scale=1.0, slot=0):
    """Stacked slabs, each rotated a little more: a twisting column."""
    n = rng.randint(14, 26)
    h = rng.uniform(2.4, 3.6) * scale
    w = rng.uniform(0.4, 0.7) * scale
    twist = rng.uniform(0.8, 2.2) * math.pi
    for i in range(n):
        z = (i + 0.5) * h / n
        taper = 1.0 - 0.35 * (i / n)
        m.box((0, 0, z), (w * taper, w * taper * rng.uniform(0.5, 0.9), h / n * 0.92), slot, twist * i / n)


GENERATORS = {
    "vehicle": (vehicle, ["carpaint", "glass", "rubber", "metal", "emissive", "emissive"]),
    "robot_arm": (robot_arm, ["carpaint", "metal", "rubber", "emissive"]),
    "torus_knot": (torus_knot, ["metal"]),
    "crystal_cluster": (crystal_cluster, ["glass", "rock"]),
    "twisted_column": (twisted_column, ["stone"]),
}


# Photoreal paint colors for vehicles and machines (toon uses the scene palette).
PAINT = [(0.55, 0.04, 0.03, 1.0), (0.03, 0.12, 0.4, 1.0), (0.85, 0.85, 0.83, 1.0), (0.02, 0.02, 0.02, 1.0),
         (0.75, 0.55, 0.05, 1.0), (0.45, 0.46, 0.48, 1.0), (0.05, 0.25, 0.12, 1.0), (0.8, 0.3, 0.02, 1.0)]


def build(builder, hero_type, rng, scale, color):
    """Build a hero; returns the object (at the origin, resting on z=0)."""
    make, kinds = GENERATORS[hero_type]
    if kinds[0] == "carpaint" and builder.style != "toon":
        color = rng.choice(PAINT)
    m = Mesh()
    make(m, rng, scale)
    colors = {"carpaint": color, "glass": (0.9, 0.95, 1.0, 1.0), "rubber": (0.03, 0.03, 0.03, 1.0),
              "metal": (0.85, 0.85, 0.88, 1.0), "rock": (0.3, 0.28, 0.26, 1.0), "stone": color}
    mats = []
    for i, kind in enumerate(kinds):
        if kind == "emissive":
            c = {4: (1.0, 0.95, 0.85, 1.0), 5: (1.0, 0.1, 0.05, 1.0)}.get(i, (0.2, 1.0, 0.4, 1.0))
            mats.append(builder.material("emissive", c))
        elif kind == "stone":
            mats.append(builder.material("concrete", color))
        else:
            mats.append(builder.material(kind, colors[kind]))
    obj = m.to_object("hero", mats, builder.scene.collection)
    obj.rotation_euler = (0, 0, rng.uniform(0, math.tau))
    builder.hero_color = list(color)
    return obj
