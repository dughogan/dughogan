"""FX kit: rigid-body destruction events.

A structure (brick wall, crate stack or drum column) stands beside the hero,
on the camera's visible side, and a heavy projectile knocks it down partway
through the clip. Every piece is its own rigid-body object, so the clip gets
per-piece Cryptomatte mattes and physically driven motion vectors.

The projectile is keyed (kinematic) on its approach and released at impact,
so Bullet carries its velocity into the collision. The simulation is baked
in build_shot.py before rendering; the bake is stored in the .blend.

Mantaflow smoke/fire isn't here yet: the pip bpy 5.2 wheel used for testing
can't bake fluids (LevelsetGrid.setConst missing), so it needs testing on a
full Blender install first.
"""

import math

import bpy
from mathutils import Vector

from kits.city import Mesh

KIT = "fx_kit"
VERSION = 1

STRUCTURES = ["brick_wall", "crate_stack", "drum_column"]


def _rigid(obj, mass=1.0, passive=False, shape="BOX", friction=0.6, bounce=0.05):
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj]):
        bpy.ops.rigidbody.object_add()
    rb = obj.rigid_body
    rb.type = "PASSIVE" if passive else "ACTIVE"
    rb.mass = mass
    rb.collision_shape = shape
    rb.friction = friction
    rb.restitution = bounce
    return rb


def _piece(builder, name, size, location, rot, mat):
    m = Mesh()
    m.box((0, 0, 0), size, 0)
    obj = m.to_object(name, [mat], builder.scene.collection)
    obj.location = location
    obj.rotation_euler = (0, 0, rot)
    builder.add_mesh(obj, "fx", "fx", "FX")
    return obj


def _structure(builder, rng, kind, origin, facing):
    """Build the structure at `origin`, its broad side facing `facing` (radians)."""
    pieces = []
    U = Vector((math.cos(facing + math.pi / 2), math.sin(facing + math.pi / 2), 0))  # along the wall
    o = Vector(origin)
    if kind == "brick_wall":
        mat = builder.material("brick" if builder.style != "toon" else "painted",
                               (0.5, 0.2, 0.12, 1.0) if builder.style != "toon" else builder.color(rng, hue=0.03))
        bw, bh, bd = 0.42, 0.2, 0.2
        cols, rows = rng.randint(5, 8), rng.randint(5, 8)
        for r in range(rows):
            off = 0.5 * bw if r % 2 else 0.0
            for c in range(cols):
                u = (c - (cols - 1) / 2) * bw + off
                p = o + U * u + Vector((0, 0, bh / 2 + r * bh))
                pieces.append(_piece(builder, f"fx_brick_{r:02d}_{c:02d}", (bw * 0.98, bd, bh * 0.98),
                                     p, facing + math.pi / 2, mat))
        mass = 2.0
    elif kind == "crate_stack":
        mat = builder.material("wood", (0.45, 0.3, 0.15, 1.0))
        s = rng.uniform(0.45, 0.6)
        base = rng.randint(3, 4)
        for r in range(base):
            for c in range(base - r):
                u = (c - (base - r - 1) / 2) * s * 1.02
                p = o + U * u + Vector((0, 0, s / 2 + r * s))
                pieces.append(_piece(builder, f"fx_crate_{r}_{c}", (s, s, s), p,
                                     facing + rng.uniform(-0.05, 0.05), mat))
        mass = 4.0
    else:  # drum_column
        mat = builder.material("metal", builder.color(rng))
        for r in range(rng.randint(4, 7)):
            m = Mesh()
            m.cylinder((0, 0, -0.3), 0.28, 0.6, 0, 16)
            obj = m.to_object(f"fx_drum_{r}", [mat], builder.scene.collection)
            obj.location = o + Vector((rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), 0.3 + r * 0.6))
            builder.add_mesh(obj, "fx", "fx", "FX")
            pieces.append(obj)
        mass = 6.0
    return pieces, mass


def build_collapse(builder, rng, frames):
    """Place a structure beside the hero and knock it down. Returns info for scene.json."""
    if builder.scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    rw = builder.scene.rigidbody_world
    f0, f1 = frames
    rw.point_cache.frame_start = f0
    rw.point_cache.frame_end = f1

    cam = builder.spec["camera"]
    cam_az = math.radians(cam["azimuth_deg"])
    side = rng.choice([-1, 1])
    ang = cam_az + side * math.radians(rng.uniform(55, 95))  # beside the hero, in view
    dist = builder.hero_size * 0.5 + rng.uniform(1.8, 3.0)
    origin = Vector((math.cos(ang) * dist, math.sin(ang) * dist, 0))
    facing = cam_az  # broad side toward the camera
    kind = rng.choice(STRUCTURES)
    pieces, mass = _structure(builder, rng, kind, origin, facing)
    for p in pieces:
        _rigid(p, mass=mass, shape="CYLINDER" if kind == "drum_column" else "BOX")

    # invisible ground collider at z=0 (kit grounds vary; this one is exact)
    g = Mesh()
    g.box((0, 0, -0.05), (80, 80, 0.1), 0)
    ground = g.to_object("fx_ground_collider", [builder.material("concrete", (0.5, 0.5, 0.5, 1.0))],
                         builder.scene.collection)
    ground.hide_render = True
    _rigid(ground, passive=True)

    # projectile: comes in from the far side of the structure and is released at impact
    impact = f0 + int((f1 - f0) * rng.uniform(0.2, 0.4))
    approach = 6
    radius = rng.uniform(0.25, 0.4)
    m = Mesh()
    from kits.nature import _icosphere
    _icosphere(m, (0, 0, 0), radius, 0, rng, rough=0.0, subdiv=3)
    ball = m.to_object("fx_projectile", [builder.material("metal", (0.2, 0.2, 0.22, 1.0))],
                       builder.scene.collection)
    builder.add_mesh(ball, "fx", "fx", "FX")
    rb = _rigid(ball, mass=mass * 15, shape="SPHERE", bounce=0.2)
    away = Vector((math.cos(facing + math.pi), math.sin(facing + math.pi), 0))  # behind the structure
    hit = origin + Vector((0, 0, rng.uniform(0.5, 1.0)))
    start = hit + away * 4.0 + Vector((0, 0, 0.8))
    rb.kinematic = True
    for f, p in ((f0, start), (max(f0, impact - approach), start), (impact, hit + away * radius)):
        ball.location = p
        ball.keyframe_insert("location", frame=f)
    rb.keyframe_insert("kinematic", frame=impact)
    rb.kinematic = False
    rb.keyframe_insert("kinematic", frame=impact + 1)
    if impact - approach > f0:  # keep the ball out of shot until its approach
        ball.hide_render = True
        ball.keyframe_insert("hide_render", frame=impact - approach - 1)
        ball.hide_render = False
        ball.keyframe_insert("hide_render", frame=impact - approach)
    return {"kit": KIT, "version": VERSION, "type": "collapse", "structure": kind,
            "pieces": len(pieces), "impact_frame": impact}


def bake(scene):
    """Bake every rigid-body cache in the scene (call after build, before render)."""
    if scene.rigidbody_world:
        with bpy.context.temp_override(scene=scene):
            bpy.ops.ptcache.bake_all(bake=True)
