"""Green/blue-screen stage for keying data.

A cyclorama (a floor that sweeps up into the back wall, so there is no
visible seam) stands behind the hero, opposite the camera. The screen is a
matte painted surface with a little self-illumination, lit unevenly like a
real backing (a soft falloff plus low-frequency blotches), and the subject
casts real shadows on its floor. Screen emission is in its own "screen"
light group.

Ground truth comes from extra view layers (passes.setup_keying):
    ViewLayer       the plate: subject in front of the screen, with spill
    Key_FG          the screen is invisible to camera but still lights the
                    subject; film transparent: exact alpha + spilled color
    Key_FG_nospill  the screen removed: the subject as it would look with no
                    screen around it (despill target), same alpha
    Key_Clean       the subject removed: the clean plate

The stage is sized after the camera is placed: every frame's frustum
corners are intersected with the wall and floor, so the screen fills the
frame on every frame of the move.
"""

import math

from mathutils import Vector

from kits.city import Mesh

KIT = "stage_kit"
VERSION = 1

SCREEN_COLLECTION = "SCREEN"
SUBJECT_COLLECTION = "SUBJECT"
SCREENS = {
    "green": (0.06, 0.42, 0.1, 1.0),
    "blue": (0.03, 0.09, 0.42, 1.0),
}
CLEAR_RADIUS = 14.0   # camera stays within this of the hero
SWEEP_RADIUS = 1.5


def plan(builder, rng):
    """Pick the screen and the wall distance before lights and camera."""
    screen = rng.choice(list(SCREENS))
    builder.studio = {"screen": screen, "back": rng.uniform(4.0, 6.0),
                      "unevenness": rng.uniform(0.05, 0.3), "markers": rng.randint(0, 8)}
    builder.clear_radius = CLEAR_RADIUS
    return builder.studio


def _cyc(m, width, depth, height, radius, segments=12):
    """Floor + curved sweep + back wall as one surface. Local frame: wall in
    the y=0 plane, floor running toward -y; u across, v along the profile (m)."""
    profile = [(-depth, 0.0), (-radius, 0.0)]
    for i in range(1, segments + 1):
        a = i / segments * math.pi / 2
        profile.append((-radius + radius * math.sin(a), radius - radius * math.cos(a)))
    profile.append((0.0, height))
    v_len = [0.0]
    for (y0, z0), (y1, z1) in zip(profile, profile[1:]):
        v_len.append(v_len[-1] + math.hypot(y1 - y0, z1 - z0))
    cols = max(8, int(width / 2))
    xs = [-width / 2 + i * width / cols for i in range(cols + 1)]
    rows = [[m.bm.verts.new((x, y, z)) for x in xs] for y, z in profile]
    for j in range(len(rows) - 1):
        for i in range(cols):
            f = m.bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
            f.smooth = True
            for loop, uv in zip(f.loops, ((xs[i], v_len[j]), (xs[i + 1], v_len[j]),
                                          (xs[i + 1], v_len[j + 1]), (xs[i], v_len[j + 1]))):
                loop[m.uv].uv = uv
    m.bm.normal_update()
    # faces must point toward the camera side (-y on the wall, +z on the floor)
    for f in m.bm.faces:
        c = f.calc_center_median()
        if f.normal.dot(Vector((0, -1, 0)) if c.z > radius else Vector((0, 0, 1))) < 0:
            f.normal_flip()


def _extents(builder, u, back):
    """Half width, height and floor depth the screen needs to fill every frame."""
    scene = builder.scene
    cam = builder.camera
    wall_point = -u * back
    side = Vector((-u.y, u.x, 0))
    half_w, top, near = 4.0, 4.0, 0.0
    for f in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(f)
        mw = cam.matrix_world
        origin = mw.translation.copy()
        near = max(near, origin.dot(u))
        for corner in cam.data.view_frame(scene=scene):
            d = (mw @ corner - origin).normalized()
            toward = d.dot(-u)
            if toward < 0.05:
                half_w = max(half_w, 60.0)  # nearly parallel to the wall: just go wide
                continue
            t = (wall_point - origin).dot(-u) / toward
            p = origin + d * t
            if p.z < 0 and d.z < 0:  # hits the floor before the wall
                p = origin + d * (-origin.z / d.z)
            half_w = max(half_w, abs(p.dot(side)))
            top = max(top, p.z)
    scene.frame_set(scene.frame_start)
    return half_w * 1.15 + 1.0, top * 1.15 + 1.0, back + near + 3.0


def build_stage(builder, rng):
    """Build the cyc, sized from the placed camera. Call after build_camera."""
    import bpy
    studio = builder.studio
    col = bpy.data.collections.new(SCREEN_COLLECTION)
    builder.scene.collection.children.link(col)
    cam_az = math.radians(builder.spec["camera"]["azimuth_deg"])
    u = Vector((math.cos(cam_az), math.sin(cam_az), 0))  # hero -> camera
    back = studio["back"]
    half_w, height, depth = _extents(builder, u, back)
    m = Mesh()
    _cyc(m, half_w * 2, depth, height, SWEEP_RADIUS)
    obj = m.to_object("cyc_screen", [builder.screen_material(studio)], col)
    # local +y (into the wall) points away from the camera
    obj.rotation_euler = (0, 0, cam_az + math.pi / 2)
    obj.location = -u * back
    obj.lightgroup = "screen"
    builder.add_mesh(obj, "environment", "screen", "ENV")
    for c in list(obj.users_collection):
        if c is not col:
            c.objects.unlink(obj)

    # tracking markers: small dark crosses on the wall, as on a real stage
    if studio["markers"]:
        markers = Mesh()
        for _ in range(studio["markers"]):
            x, z = rng.uniform(-half_w * 0.6, half_w * 0.6), rng.uniform(1.5, max(2.0, height * 0.8))
            markers.box((x, -0.01, z), (0.2, 0.01, 0.04), 0)
            markers.box((x, -0.01, z), (0.04, 0.01, 0.2), 0)
        mk = markers.to_object("tracking_markers", [builder.material("painted", (0.03, 0.03, 0.03, 1.0))], col)
        mk.parent = obj
        builder.add_mesh(mk, "environment", "painted", None)
        for c in list(mk.users_collection):
            if c is not col:
                c.objects.unlink(mk)
    studio.update({"width": round(half_w * 2, 2), "height": round(height, 2), "depth": round(depth, 2)})
    return {"kit": KIT, "version": VERSION}


def move_subject(builder):
    """Put the hero (and everything parented under it) into SUBJECT, so the
    clean-plate layer can exclude it."""
    import bpy
    col = bpy.data.collections.new(SUBJECT_COLLECTION)
    builder.scene.collection.children.link(col)
    root = builder.groups["HERO"]
    stack = [root]
    while stack:
        obj = stack.pop()
        stack.extend(obj.children)
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        col.objects.link(obj)
