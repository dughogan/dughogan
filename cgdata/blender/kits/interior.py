"""Procedural interior kit: a room with open windows, furniture and practicals.

A loft-style room is built around the hero: wood floor, plaster walls with
open window bays (daylight comes in through real openings, so the sun stays
the key), a ceiling, baseboards and a door. Furniture is placed along the
walls and in groupings, every piece its own object so Cryptomatte gives a
matte per piece: tables, chairs, a sofa, shelving with books, floor lamps
(real practical lights), rugs, framed pictures and potted plants.

The camera's clear zone is set from the room size, and scatter stays off the
camera's side of the hero, as in the nature kit.
"""

import math

from mathutils import Vector

from kits.city import Mesh
from kits.nature import shrub

KIT = "interior_kit"
VERSION = 1

WALL_T = 0.25
HERO_CLEAR = 3.2      # furniture keeps this far from the hero


# ------------------------------------------------------------------ shell

def _wall(m, a, b, height, openings, mat_wall, mat_trim):
    """A wall from a to b (floor level), with rectangular openings
    [(u0, u1, v0, v1)] cut through it and trimmed reveals."""
    a, b = Vector(a), Vector(b)
    U = (b - a).normalized()
    length = (b - a).length
    N = Vector((-U.y, U.x, 0))  # inward normal (walls are built counterclockwise)
    up = Vector((0, 0, 1))

    def P(u, v, d=0.0):
        return a + U * u + up * v - N * d

    # split the wall into vertical strips at opening edges
    cuts = sorted({0.0, length, *[c for o in openings for c in o[:2]]})
    for u0, u1 in zip(cuts, cuts[1:]):
        holes = [o for o in openings if o[0] <= u0 and o[1] >= u1]
        spans, v = [], 0.0
        for o in sorted(holes, key=lambda o: o[2]):
            spans.append((v, o[2]))
            v = o[3]
        spans.append((v, height))
        for v0, v1 in spans:
            if v1 - v0 > 1e-4:
                m.quad([P(u0, v0), P(u1, v0), P(u1, v1), P(u0, v1)],
                       [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], mat_wall, N)
                m.quad([P(u1, v0, WALL_T), P(u0, v0, WALL_T), P(u0, v1, WALL_T), P(u1, v1, WALL_T)],
                       [(u1, v0), (u0, v0), (u0, v1), (u1, v1)], mat_wall, -N)
    for u0, u1, v0, v1 in openings:  # reveals
        for pts, facing in (
            ([P(u0, v0), P(u1, v0), P(u1, v0, WALL_T), P(u0, v0, WALL_T)], up),
            ([P(u0, v1, WALL_T), P(u1, v1, WALL_T), P(u1, v1), P(u0, v1)], -up),
            ([P(u0, v0, WALL_T), P(u0, v1, WALL_T), P(u0, v1), P(u0, v0)], U),
            ([P(u1, v0), P(u1, v1), P(u1, v1, WALL_T), P(u1, v0, WALL_T)], -U),
        ):
            m.quad(pts, [(0, 0), (1, 0), (1, WALL_T), (0, WALL_T)], mat_trim, facing)
    # baseboard
    m.box(a + U * (length / 2) + N * 0.01 + up * 0.06, (length, 0.03, 0.12), mat_trim,
          math.atan2(U.y, U.x))


def room_shell(builder, rng, half_w, half_d, height, col):
    m = Mesh()
    WALL, TRIM, FLOOR, CEILING, OUTSIDE = range(5)
    corners = [(-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)]
    door_wall = rng.randrange(4)
    door_span = None
    for i in range(4):
        a, b = Vector((*corners[i], 0)), Vector((*corners[(i + 1) % 4], 0))
        length = (b - a).length
        openings = []
        if i == door_wall:
            u = rng.uniform(1.5, length - 2.5)
            openings.append((u, u + 1.0, 0.0, 2.2))
            door_span = (a, b, u, u + 1.0)
        else:
            bays = max(1, int(length // rng.uniform(3.0, 4.5)))
            for k in range(bays):
                c = (k + 0.5) * length / bays
                w = min(length / bays * 0.6, rng.uniform(1.4, 2.4))
                openings.append((c - w / 2, c + w / 2, rng.uniform(0.6, 0.9), height - rng.uniform(0.4, 0.8)))
        _wall(m, a, b, height, openings, WALL, TRIM)
    m.box((0, 0, -0.05), (2 * half_w, 2 * half_d, 0.1), FLOOR)
    m.box((0, 0, -0.2), (200, 200, 0.1), OUTSIDE)  # what the windows look out onto
    m.box((0, 0, height + 0.05), (2 * half_w + 2 * WALL_T, 2 * half_d + 2 * WALL_T, 0.1), CEILING)
    # exposed ceiling beams, loft-style
    if rng.random() < 0.6:
        for x in [(-half_w + (k + 0.5) * 2 * half_w / 5) for k in range(5)]:
            m.box((x, 0, height - 0.15), (0.25, 2 * half_d, 0.3), TRIM)
    wall_color = builder.color(rng) if builder.style == "toon" else \
        rng.choice([(0.78, 0.76, 0.72, 1.0), (0.62, 0.66, 0.64, 1.0), (0.74, 0.68, 0.6, 1.0)])
    mats = [builder.material("painted", wall_color),
            builder.material("painted", (0.85, 0.84, 0.8, 1.0)),
            builder.material("wood", (0.42, 0.27, 0.15, 1.0)),
            builder.material("painted", (0.88, 0.87, 0.85, 1.0)),
            builder.material("ground", (0.25, 0.3, 0.2, 1.0))]
    obj = m.to_object("room_shell", mats, col)
    builder.add_mesh(obj, "environment", "painted", "ENV")
    return door_span


# -------------------------------------------------------------- furniture

def table(m, rng, top=0, legs=1):
    w, d, h = rng.uniform(1.2, 2.0), rng.uniform(0.7, 1.0), rng.uniform(0.72, 0.78)
    m.box((0, 0, h - 0.025), (w, d, 0.05), top)
    for sx in (-1, 1):
        for sy in (-1, 1):
            m.box((sx * (w / 2 - 0.06), sy * (d / 2 - 0.06), (h - 0.05) / 2), (0.05, 0.05, h - 0.05), legs)
    return max(w, d)


def chair(m, rng, seat=0, frame=1):
    s, h = rng.uniform(0.42, 0.5), 0.45
    m.box((0, 0, h), (s, s, 0.05), seat)
    m.box((0, s / 2 - 0.02, h + 0.4), (s, 0.04, 0.8 - 0.05), frame)
    for sx in (-1, 1):
        for sy in (-1, 1):
            m.box((sx * (s / 2 - 0.03), sy * (s / 2 - 0.03), h / 2), (0.035, 0.035, h), frame)
    return s


def sofa(m, rng, fabric=0, legs=1):
    w, d = rng.uniform(1.8, 2.6), rng.uniform(0.85, 1.0)
    m.box((0, 0, 0.28), (w, d, 0.3), fabric)
    m.box((0, d / 2 - 0.12, 0.6), (w, 0.24, 0.5), fabric)
    for sx in (-1, 1):
        m.box((sx * (w / 2 - 0.1), 0, 0.45), (0.2, d, 0.35), fabric)
    for k in range(2 if w < 2.2 else 3):  # cushions
        cw = (w - 0.4) / (2 if w < 2.2 else 3)
        m.box((-w / 2 + 0.2 + cw * (k + 0.5), -0.05, 0.48), (cw * 0.96, d - 0.3, 0.12), fabric)
    for sx in (-1, 1):
        for sy in (-1, 1):
            m.box((sx * (w / 2 - 0.08), sy * (d / 2 - 0.08), 0.06), (0.05, 0.05, 0.12), legs)
    return w


def shelving(m, rng, frame=0, books=1):
    w, d, h = rng.uniform(1.0, 2.0), 0.35, rng.uniform(1.6, 2.2)
    for sx in (-1, 1):
        m.box((sx * (w / 2 - 0.02), 0, h / 2), (0.04, d, h), frame)
    levels = rng.randint(4, 6)
    for k in range(levels):
        z = k * (h - 0.05) / (levels - 1) + 0.02
        m.box((0, 0, z), (w, d, 0.03), frame)
        if k < levels - 1:
            x = -w / 2 + 0.05
            while x < w / 2 - 0.1:
                bw = rng.uniform(0.02, 0.05)
                bh = rng.uniform(0.18, min(0.3, (h - 0.05) / (levels - 1) - 0.04))
                if rng.random() < 0.85:
                    m.box((x + bw / 2, rng.uniform(-0.03, 0.03), z + 0.015 + bh / 2), (bw, 0.22, bh), books)
                x += bw + 0.003
    return w


def floor_lamp(m, rng, pole=0, shade=1):
    h = rng.uniform(1.4, 1.75)
    m.cylinder((0, 0, 0), 0.16, 0.03, pole, 16)
    m.cylinder((0, 0, 0), 0.015, h, pole, 8)
    m.cylinder((0, 0, h - 0.05), 0.2, 0.28, shade, 20)
    return h + 0.05


def rug(m, rng, mat=0):
    w, d = rng.uniform(2.0, 3.2), rng.uniform(1.5, 2.4)
    m.box((0, 0, 0.005), (w, d, 0.01), mat)
    return max(w, d)


# ------------------------------------------------------------------ build

def build_interior(builder, rng, density):
    col = builder.scene.collection
    half_w, half_d = rng.uniform(7.0, 10.0), rng.uniform(6.0, 9.0)
    height = rng.uniform(3.6, 5.0)
    door_span = room_shell(builder, rng, half_w, half_d, height, col)
    builder.room = {"half_w": half_w, "half_d": half_d, "height": height}
    builder.clear_radius = min(half_w, half_d) - 0.6

    cam = builder.spec["camera"]
    cam_az = math.radians(cam["azimuth_deg"])
    keep_out = math.radians(70 + (90 * cam["travel"] if cam["move"] == "orbit" else 0))

    def clear_of_camera(x, y):
        ang = math.atan2(y, x)
        return abs((ang - cam_az + math.pi) % math.tau - math.pi) > keep_out

    toon = builder.style == "toon"
    wood = builder.material("wood", builder.color(rng, hue=0.08) if toon else (0.35, 0.22, 0.12, 1.0))
    metal = builder.material("metal", (0.15, 0.15, 0.16, 1.0))
    fabric = builder.material("fabric", builder.color(rng))
    rug_mat = builder.material("fabric", builder.color(rng))
    books = builder.material("painted", builder.color(rng))
    shade = builder.material("emissive", (1.0, 0.82, 0.6, 1.0))
    pot = builder.material("concrete", (0.6, 0.45, 0.35, 1.0))
    leaves = builder.material("foliage", builder.color(rng, hue=rng.uniform(0.24, 0.32)))
    frames = [builder.material("painted", builder.color(rng)) for _ in range(3)]

    placed = []

    def free(x, y, r):
        if math.hypot(x, y) < HERO_CLEAR + r or not clear_of_camera(x, y):
            return False
        return all(math.hypot(x - px, y - py) > r + pr + 0.3 for px, py, pr in placed)

    def put(name, mesh, mats, x, y, rot, r, role="prop", kind="wood"):
        obj = mesh.to_object(name, mats, col)
        obj.location = (x, y, 0)
        obj.rotation_euler = (0, 0, rot)
        builder.add_mesh(obj, "environment", kind, "ENV")
        placed.append((x, y, r))
        return obj

    def along_wall(depth):
        """A random spot `depth` in from a wall. Pieces are modeled with their
        back toward +Y; the rotation turns that back to face the wall."""
        side = rng.randrange(4)
        if side in (0, 2):
            x, y = rng.uniform(-half_w + 1, half_w - 1), (-1 if side == 0 else 1) * (half_d - depth)
            rot = math.pi if side == 0 else 0.0
        else:
            x, y = (1 if side == 1 else -1) * (half_w - depth), rng.uniform(-half_d + 1, half_d - 1)
            rot = -math.pi / 2 if side == 1 else math.pi / 2
        return x, y, rot

    def try_place(n, make, mats, depth=None, kind="wood"):
        for i in range(n):
            for _ in range(30):
                m = Mesh()
                r = make(m, rng) / 2
                if depth is None:
                    x = rng.uniform(-half_w + r + 0.5, half_w - r - 0.5)
                    y = rng.uniform(-half_d + r + 0.5, half_d - r - 0.5)
                    rot = rng.uniform(0, math.tau)
                else:
                    x, y, rot = along_wall(depth)
                if free(x, y, r):
                    put(f"{make.__name__}_{i:02d}", m, mats, x, y, rot, r, kind=kind)
                    break
                m.bm.free()

    count = lambda k: max(1, round(k * density))  # noqa: E731
    try_place(count(2), shelving, [wood, books], depth=0.45)
    try_place(count(1), sofa, [fabric, metal], depth=0.7, kind="fabric")
    try_place(count(2), table, [wood, metal])
    try_place(count(4), chair, [wood, metal])
    try_place(count(2), rug, [rug_mat], kind="fabric")

    for i in range(count(3)):  # floor lamps: real practical lights
        for _ in range(30):
            m = Mesh()
            h = floor_lamp(m, rng, 0, 1)
            x = rng.uniform(-half_w + 0.8, half_w - 0.8)
            y = rng.uniform(-half_d + 0.8, half_d - 0.8)
            if free(x, y, 0.3):
                obj = put(f"floor_lamp_{i:02d}", m, [metal, shade], x, y, 0, 0.3)
                builder.assign_practical(obj)
                builder.point_light(f"lamp_light_{i:02d}", (x, y, h - 0.2), 60.0, (1.0, 0.8, 0.55))
                break
            m.bm.free()

    for i in range(count(3)):  # potted plants
        for _ in range(30):
            x = rng.uniform(-half_w + 0.8, half_w - 0.8)
            y = rng.uniform(-half_d + 0.8, half_d - 0.8)
            if free(x, y, 0.5):
                m = Mesh()
                m.cylinder((0, 0, 0), 0.25, 0.45, 0, 16)
                shrub(m, rng, (0, 0, 0.45), rng.uniform(0.5, 0.9), 1)
                put(f"plant_{i:02d}", m, [pot, leaves], x, y, 0, 0.5, kind="foliage")
                break

    # framed pictures on the door wall (the only wall without windows), clear of the door
    a, b, d0, d1 = door_span
    U = (b - a).normalized()
    N = Vector((-U.y, U.x, 0))
    length = (b - a).length
    hung = []
    for i in range(count(4)):
        w, h = rng.uniform(0.5, 1.2), rng.uniform(0.4, 0.9)
        for _ in range(30):
            u = rng.uniform(w / 2 + 0.3, length - w / 2 - 0.3)
            if abs(u - (d0 + d1) / 2) > (d1 - d0) / 2 + w / 2 + 0.3 and \
                    all(abs(u - hu) > (w + hw) / 2 + 0.3 for hu, hw in hung):
                break
        else:
            continue
        hung.append((u, w))
        m = Mesh()
        m.box((0, 0, 0), (w, 0.03, h), 0)
        m.box((0, 0.017, 0), (w - 0.1, 0.005, h - 0.1), 1)  # the picture faces +Y (into the room)
        obj = m.to_object(f"picture_{i:02d}", [wood, rng.choice(frames)], col)
        p = a + U * u + N * 0.02
        obj.location = (p.x, p.y, rng.uniform(1.4, 1.8))
        obj.rotation_euler = (0, 0, math.atan2(N.y, N.x) - math.pi / 2)
        builder.add_mesh(obj, "environment", "painted", "ENV")

    return {"kit": KIT, "version": VERSION, "room": builder.room, "pieces": len(placed)}
