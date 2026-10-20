"""Procedural stylized character: rigged body, walk and idle cycles, joint data.

A segmented figure (mannequin-like in photoreal, chunky big-headed in toon)
is built on a 17-bone armature. Each body part is its own object parented
rigidly to its bone, so Cryptomatte gives a matte per part. Animation is
keyed procedurally:

    walk   a straight walk through the hero position (legs, arms, hip bob)
    idle   breathing, weight shift, head turns

Joint positions (bone heads and tails, world space) are recorded for every
frame; export.py projects them through the camera into a pose-control video.
The character faces +Y; limbs hang along -Z, so a +X rotation swings a limb
forward.
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from kits.city import Mesh
from kits.nature import _cone, _icosphere

KIT = "character_kit"
VERSION = 1

# bone: (parent, head, tail) in units of character height, rest pose.
SKELETON = {
    "root": (None, (0, 0, 0.0), (0, 0.1, 0.0)),
    "hips": ("root", (0, 0, 0.53), (0, 0, 0.6)),
    "spine": ("hips", (0, 0, 0.6), (0, 0, 0.7)),
    "chest": ("spine", (0, 0, 0.7), (0, 0, 0.82)),
    "neck": ("chest", (0, 0, 0.82), (0, 0, 0.87)),
    "head": ("neck", (0, 0, 0.87), (0, 0, 1.0)),
    "upper_arm.L": ("chest", (0.12, 0, 0.8), (0.14, 0, 0.62)),
    "forearm.L": ("upper_arm.L", (0.14, 0, 0.62), (0.15, 0, 0.47)),
    "hand.L": ("forearm.L", (0.15, 0, 0.47), (0.15, 0, 0.41)),
    "upper_arm.R": ("chest", (-0.12, 0, 0.8), (-0.14, 0, 0.62)),
    "forearm.R": ("upper_arm.R", (-0.14, 0, 0.62), (-0.15, 0, 0.47)),
    "hand.R": ("forearm.R", (-0.15, 0, 0.47), (-0.15, 0, 0.41)),
    "thigh.L": ("hips", (0.06, 0, 0.52), (0.065, 0, 0.28)),
    "shin.L": ("thigh.L", (0.065, 0, 0.28), (0.07, 0, 0.05)),
    "foot.L": ("shin.L", (0.07, 0, 0.05), (0.07, 0.09, 0.02)),
    "thigh.R": ("hips", (-0.06, 0, 0.52), (-0.065, 0, 0.28)),
    "shin.R": ("thigh.R", (-0.065, 0, 0.28), (-0.07, 0, 0.05)),
    "foot.R": ("shin.R", (-0.07, 0, 0.05), (-0.07, 0.09, 0.02)),
}

# OpenPose-style limbs for the pose video: the single source is
# cgdata/blender_constants.py (importable without bpy).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[3]))
from cgdata.blender_constants import POSE_LIMBS as LIMBS  # noqa: E402


def _rig(name, height, col):
    data = bpy.data.armatures.new(name)
    arm = bpy.data.objects.new(name, data)
    col.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for bone, (parent, head, tail) in SKELETON.items():
        eb = data.edit_bones.new(bone)
        eb.head = Vector(head) * height
        eb.tail = Vector(tail) * height
        if parent:
            eb.parent = data.edit_bones[parent]
            eb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
    return arm


def _part(arm, bone, mesh, mats, col, name):
    obj = mesh.to_object(name, mats, col)
    obj.parent = arm
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    obj.matrix_world = Matrix.Identity(4)  # keep the rest-pose placement
    return obj


def _limb(height, bone, r0, r1, slot):
    """A tapered segment along a bone's rest head->tail."""
    _, head, tail = SKELETON[bone]
    m = Mesh()
    _cone(m, Vector(head) * height, Vector(tail) * height, r0 * height, r1 * height, slot, 14)
    return m


def build_character(builder, rng, toon):
    col = builder.scene.collection
    height = rng.uniform(1.65, 1.9)
    head_scale = 1.45 if toon else 1.0
    arm = _rig("character_rig", height, col)

    skin = builder.material("sss", builder.color(rng, hue=rng.uniform(0.04, 0.09)) if toon
                            else rng.choice([(0.8, 0.62, 0.5, 1.0), (0.55, 0.38, 0.28, 1.0),
                                             (0.35, 0.22, 0.15, 1.0), (0.9, 0.75, 0.65, 1.0)]))
    shirt = builder.material("fabric", builder.color(rng))
    pants = builder.material("fabric", builder.color(rng))
    shoes = builder.material("rubber", (0.05, 0.05, 0.05, 1.0))

    parts = []

    def add(bone, mesh, mats):
        parts.append(_part(arm, bone, mesh, mats, col, f"char_{bone}"))

    # torso: hips, belly, chest as soft boxes
    for bone, w, d, slot in (("hips", 0.16, 0.1, 1), ("spine", 0.15, 0.09, 0), ("chest", 0.19, 0.11, 0)):
        _, head, tail = SKELETON[bone]
        m = Mesh()
        c = (Vector(head) + Vector(tail)) / 2 * height
        _icosphere(m, c, 1.0, slot, rng, rough=0.05,
                   squash=(w * height, d * height, (tail[2] - head[2]) * height * 0.75), subdiv=2)
        add(bone, m, [shirt, pants])
    add("neck", _limb(height, "neck", 0.025, 0.022, 0), [skin])
    m = Mesh()
    _, hh, ht = SKELETON["head"]
    hc = (Vector(hh) + Vector(ht)) / 2 * height
    hr = 0.065 * height * head_scale
    _icosphere(m, hc + Vector((0, 0, hr * 0.15)), hr, 0, rng, rough=0.02, squash=(0.9, 1.0, 1.1), subdiv=3)
    if toon:  # simple eyes
        for side in (-1, 1):
            _icosphere(m, hc + Vector((side * hr * 0.35, hr * 0.85, hr * 0.3)), hr * 0.16, 1, rng, rough=0.0)
    add("head", m, [skin, builder.material("painted", (0.02, 0.02, 0.02, 1.0))])
    for side in ("L", "R"):
        add(f"upper_arm.{side}", _limb(height, f"upper_arm.{side}", 0.035, 0.03, 0), [shirt])
        add(f"forearm.{side}", _limb(height, f"forearm.{side}", 0.028, 0.024, 0), [skin])
        add(f"hand.{side}", _limb(height, f"hand.{side}", 0.026, 0.02, 0), [skin])
        add(f"thigh.{side}", _limb(height, f"thigh.{side}", 0.05, 0.04, 0), [pants])
        add(f"shin.{side}", _limb(height, f"shin.{side}", 0.038, 0.03, 0), [pants])
        m = Mesh()
        _, fh, ft = SKELETON[f"foot.{side}"]
        m.box((Vector(fh) + Vector(ft)) / 2 * height + Vector((0, 0.02 * height, -0.01 * height)),
              (0.06 * height, 0.15 * height, 0.045 * height), 0)
        add(f"foot.{side}", m, [shoes])
    return arm, parts, height


# --------------------------------------------------------------- animation

def walk_length(height, frames, stride_period=25.0):
    """Distance a walk covers over `frames` (first, last), at natural cadence."""
    return 0.87 * height * (frames[1] - frames[0]) / stride_period


def animate(arm, rng, frames, mode, height):
    """Key a walk or an idle on the rig across `frames` (first, last).
    Returns the root's start and end (rig space) for a walk, else None."""
    f0, f1 = frames
    pb = arm.pose.bones
    stride_period = rng.uniform(22, 28)  # frames per full gait cycle at 24 fps
    # Travel matches the legs: with +/-0.45 rad thigh swing a step is about
    # 0.43 x height, two steps per cycle; anything else makes the feet slide.
    path = 0.87 * height * (f1 - f0) / stride_period
    phase0 = rng.uniform(0, math.tau)
    for f in range(f0, f1 + 1):
        t = (f - f0) / max(f1 - f0, 1)
        ph = phase0 + (f - f0) / stride_period * math.tau
        if mode == "walk":
            swing, s2 = math.sin(ph), math.sin(2 * ph)
            pb["root"].location = (0, -path / 2 + path * t, 0)  # bone-local Y = world +Y here
            # hips point up: their local Y is world Z
            pb["hips"].location = (0, 0.012 * height * (1 - abs(math.cos(ph))), 0)
            pb["hips"].rotation_euler = (0, 0.06 * swing, 0)
            pb["thigh.L"].rotation_euler = (0.45 * swing, 0, 0)
            pb["thigh.R"].rotation_euler = (-0.45 * swing, 0, 0)
            pb["shin.L"].rotation_euler = (-0.55 * max(0.0, -math.sin(ph + 0.9)), 0, 0)
            pb["shin.R"].rotation_euler = (-0.55 * max(0.0, math.sin(ph + 0.9)), 0, 0)
            pb["upper_arm.L"].rotation_euler = (-0.35 * swing, 0, 0)
            pb["upper_arm.R"].rotation_euler = (0.35 * swing, 0, 0)
            pb["forearm.L"].rotation_euler = (0.25 + 0.15 * s2, 0, 0)
            pb["forearm.R"].rotation_euler = (0.25 - 0.15 * s2, 0, 0)
            pb["chest"].rotation_euler = (0.04, -0.05 * swing, 0)
        else:  # idle
            breathe = math.sin((f - f0) / 48 * math.tau)
            shift = math.sin((f - f0) / 90 * math.tau + phase0)
            pb["chest"].rotation_euler = (0.02 * breathe, 0, 0)
            pb["hips"].rotation_euler = (0, 0.04 * shift, 0)
            # turning the head is a rotation about the (vertical) bone axis, local Y
            pb["head"].rotation_euler = (0.05 * math.sin(ph * 0.3), 0.5 * math.sin((f - f0) / 70 * math.tau + phase0), 0)
            pb["upper_arm.L"].rotation_euler = (0.05 * breathe, 0, -0.08)
            pb["upper_arm.R"].rotation_euler = (0.05 * breathe, 0, 0.08)
        for bone in pb:
            bone.keyframe_insert("rotation_euler", frame=f)
            bone.keyframe_insert("location", frame=f)
    return (Vector((0, -path / 2, 0)), Vector((0, path / 2, 0))) if mode == "walk" else None


def joint_track(arm, scene, frames):
    """World-space head/tail of every bone, per frame (for pose control data)."""
    out = {}
    for f in range(frames[0], frames[1] + 1):
        scene.frame_set(f)
        mw = arm.matrix_world
        out[f] = {b.name: [list(mw @ b.head), list(mw @ b.tail)] for b in arm.pose.bones}
    scene.frame_set(frames[0])
    return out
