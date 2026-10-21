"""Procedural scene assembly: environment, hero, props, lights, camera.

Everything is generated from the shot spec's seeds with Blender primitives,
modifiers and procedural materials, so the scene is fully owned and fully
reproducible. Objects are parented under ENV / PROPS / HERO / LIGHTS empties so
Cryptomatte Asset mattes come out per asset group.
"""

import math
import random

import bpy
from mathutils import Vector

from kits import city as city_kit
from kits import character as character_kit
from kits import fx as fx_kit
from kits import heroes as hero_kit
from kits import interior as interior_kit
from kits import nature as nature_kit
from kits import stage as stage_kit
from materials import hsv, make_material, screen_material
from passes import assign_lightgroup, atmosphere_collection, setup_keying

# Radius around the hero kept free of environment geometry for the camera.
CLEAR_RADIUS = 18.0

# Blender 5.2's multiple-scattering sky is far brighter per unit strength
# than a sun lamp in W/m^2 (strength 0.3 outshone a 2.2 sun in a sun-only vs
# sky-only test), so the photoreal sky is scaled down to sit under the key.
PHYSICAL_SKY_SCALE = 0.2

PASS_INDEX = {"hero": 1, "prop": 2, "environment": 3, "ground": 4, "practical": 5, "fx": 6}

# Fraction of windows / street lamps lit, per time of day.
LIT_FRACTION = {"morning": 0.1, "noon": 0.05, "golden_hour": 0.25, "dusk": 0.5}

# Sun elevation (deg), sun color, sun strength, sky strength per time of day.
# Calibrated 2026-10-19 from light-group means in city renders: the physical
# sky was supplying ~85% of the light and flattening everything, so it is
# kept well below the sun; at dusk the practicals carry the frame. Sky
# strengths are scaled by PHYSICAL_SKY_SCALE for the physical (photoreal) sky.
TIME_OF_DAY = {
    "morning": (22.0, (1.0, 0.85, 0.7), 2.6, 0.3),
    "noon": (65.0, (1.0, 0.97, 0.92), 3.0, 0.35),
    "golden_hour": (14.0, (1.0, 0.65, 0.4), 2.8, 0.18),
    "dusk": (6.0, (0.9, 0.5, 0.45), 1.2, 0.08),
}


def _dist_to_segment(p, a, b):
    a, b = Vector((a.x, a.y, 0)), Vector((b.x, b.y, 0))
    ab = b - a
    t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


class Builder:
    def __init__(self, spec):
        self.spec = spec
        self.style = spec["style"]
        self.scene = bpy.context.scene
        self.objects = []  # (name, role, material kind) for meta.json
        self._materials = {}
        self.groups = {}
        self.lights = []
        self.uses = {"kits": {}}  # asset kits (and versions) this shot was built from
        self.hero_path = None     # a walking character's start and end (world)
        self.fx = None            # FX event info, for scene.json
        self.room = None          # set by the interior kit: half_w, half_d, height
        self.studio = None        # set by the stage kit (green/blue-screen shots)
        self.clear_radius = CLEAR_RADIUS

    # ---------------------------------------------------------------- helpers

    def group(self, name):
        if name not in self.groups:
            empty = bpy.data.objects.new(name, None)
            self.scene.collection.objects.link(empty)
            self.groups[name] = empty
        return self.groups[name]

    def material(self, kind, color):
        # Toon palettes read better saturated and bright; photoreal muted.
        key = (kind, tuple(round(c, 3) for c in color))
        if key not in self._materials:
            name = f"{self.style}_{kind}_{len(self._materials):03d}"
            mat = make_material(name, self.style, kind, color)
            mat.pass_index = len(self._materials) + 1
            self._materials[key] = mat
        return self._materials[key]

    def color(self, rng, hue=None):
        h = rng.random() if hue is None else hue
        if self.style == "toon":
            return hsv(h, rng.uniform(0.45, 0.8), rng.uniform(0.6, 0.95))
        return hsv(h, rng.uniform(0.05, 0.35), rng.uniform(0.25, 0.7))

    def add(self, obj, role, kind, mat, parent):
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        obj.pass_index = PASS_INDEX[role]
        obj.parent = self.groups[parent] if parent in self.groups else self.group(parent)
        self.objects.append({"name": obj.name, "role": role, "material": mat.name, "kind": kind})
        return obj

    def add_mesh(self, obj, role, kind, parent):
        """Register a kit object that already carries its own material slots.
        parent=None keeps the object's existing parent (e.g. a rig bone)."""
        obj.pass_index = PASS_INDEX[role]
        if parent is not None:
            obj.parent = self.group(parent)
        self.objects.append({"name": obj.name, "role": role, "kind": kind,
                             "material": [m.name for m in obj.data.materials]})
        return obj

    def screen_material(self, studio):
        color = stage_kit.SCREENS[studio["screen"]]
        mat = screen_material(f"screen_{studio['screen']}", color, studio["unevenness"])
        mat.pass_index = len(self._materials) + 1
        self._materials[("screen", studio["screen"])] = mat
        return mat

    def assign_practical(self, obj):
        """Emission on this object (lit windows, lamp heads) is a practical light."""
        assign_lightgroup(obj, "practical")

    def point_light(self, name, location, energy, color, group="practical"):
        data = bpy.data.lights.new(name, "POINT")
        data.energy = energy
        data.color = color
        data.shadow_soft_size = 0.15
        obj = bpy.data.objects.new(name, data)
        obj.visible_camera = False  # the visible cue is the emissive lamp head
        obj.location = location
        self.scene.collection.objects.link(obj)
        obj.parent = self.group("LIGHTS")
        assign_lightgroup(obj, group)
        self.lights.append({"name": name, "type": "POINT", "group": group, "energy": energy,
                            "color": list(color)})
        return obj

    def _primitive(self, op, name, location, **kw):
        op(location=location, **kw)
        obj = bpy.context.active_object
        obj.name = name
        return obj

    def _smooth(self, obj):
        for poly in obj.data.polygons:
            poly.use_smooth = True

    def _displace(self, obj, strength, size, seed, levels=3):
        sub = obj.modifiers.new("subdiv", "SUBSURF")
        sub.levels = sub.render_levels = levels
        tex = bpy.data.textures.new(f"{obj.name}_noise", "CLOUDS")
        tex.noise_scale = size
        tex.noise_depth = 3
        # Sample the noise through a per-object offset empty so displaced
        # shapes never repeat between objects or shots.
        offset = bpy.data.objects.new(f"{obj.name}_noise_offset", None)
        offset.location = (seed % 997, (seed // 997) % 991, 0)
        offset.parent = obj  # moving the object must not change its shape
        self.scene.collection.objects.link(offset)
        disp = obj.modifiers.new("displace", "DISPLACE")
        disp.texture = tex
        disp.strength = strength
        disp.mid_level = 0.5
        disp.texture_coords = "OBJECT"
        disp.texture_coords_object = offset

    # ------------------------------------------------------------ environment

    def build_environment(self):
        env = self.spec["environment"]
        rng = random.Random(env["seed"])
        extent = env["extent"]
        if env["type"] == "city_block":
            lit = LIT_FRACTION[self.spec["lighting"]["time_of_day"]]
            info = city_kit.build_city(self, rng, extent, env["density"], lit)
            self.uses["kits"][info["kit"]] = info["version"]
            return
        if env["type"] == "greenscreen":
            stage_kit.plan(self, rng)  # the cyc itself is built once the camera is placed
            self.uses["kits"][stage_kit.KIT] = stage_kit.VERSION
            return
        if env["type"] == "interior":
            info = interior_kit.build_interior(self, rng, env["density"])
            self.uses["kits"][info["kit"]] = info["version"]
            return

        info = nature_kit.build_nature(self, rng, extent, env["density"], env["type"])
        self.uses["kits"][info["kit"]] = info["version"]

    # ------------------------------------------------------------------- hero

    def build_hero(self):
        hero = self.spec["hero"]
        rng = random.Random(self.spec["seed"] * 31 + 7)
        s = hero["scale"]
        color = self.color(rng, hue=hero["hue"])
        self.hero_color = list(color)  # generated heroes may repaint; captions read this
        t = hero["type"]
        if t == "character":
            self._build_character(rng)
            return
        if t in hero_kit.GENERATORS:
            self._build_generated_hero(t, rng, s, color)
            return
        if t == "glass_sculpture":
            obj = self._primitive(
                bpy.ops.mesh.primitive_torus_add, "hero", (0, 0, s), major_radius=s * 0.7, minor_radius=s * 0.25
            )
            obj.rotation_euler = (math.radians(70), 0, rng.uniform(0, math.tau))
            kind = "glass"
        elif t == "chrome_sculpture":
            obj = self._primitive(bpy.ops.mesh.primitive_uv_sphere_add, "hero", (0, 0, s), radius=s * 0.8)
            self._displace(obj, s * 0.3, 0.6, self.spec["seed"], levels=2)
            kind = "metal"
            color = hsv(hero["hue"], 0.1, 0.9)
        elif t == "sss_blob":
            obj = self._primitive(bpy.ops.mesh.primitive_ico_sphere_add, "hero", (0, 0, s), subdivisions=3, radius=s * 0.8)
            self._displace(obj, s * 0.4, 0.9, self.spec["seed"], levels=2)
            kind = "sss"
        elif t == "neon_totem":
            obj = self._primitive(
                bpy.ops.mesh.primitive_cylinder_add, "hero", (0, 0, s * 1.5), radius=s * 0.3, depth=s * 3
            )
            kind = "painted"
            ring_color = hsv(hero["hue"] + 0.5, 0.8, 1.0)
            for i in range(4):
                ring = self._primitive(
                    bpy.ops.mesh.primitive_torus_add,
                    f"hero_ring_{i}",
                    (0, 0, s * (0.5 + i * 0.7)),
                    major_radius=s * 0.42,
                    minor_radius=s * 0.05,
                )
                self.add(ring, "hero", "emissive", self.material("emissive", ring_color), "HERO")
                assign_lightgroup(ring, "practical")
        else:  # stone_monolith
            obj = self._primitive(bpy.ops.mesh.primitive_cube_add, "hero", (0, 0, s * 1.5))
            obj.scale = (s * 0.5, s * 0.25, s * 1.5)
            bev = obj.modifiers.new("bevel", "BEVEL")
            bev.width = 0.1
            bev.segments = 3
            kind = "rock"
        self._smooth(obj)
        self.add(obj, "hero", kind, self.material(kind, color), "HERO")
        bpy.context.view_layer.update()
        if t != "neon_totem":  # the totem's rings are placed relative to its base
            self._settle(obj)
        self._measure_hero(obj)

    def _build_generated_hero(self, t, rng, scale, color):
        """A hero from the hero kit (vehicles, machines, sculptural pieces)."""
        obj = hero_kit.build(self, t, rng, 1.0 if t == "vehicle" else scale, color)
        kind = hero_kit.GENERATORS[t][1][0]
        self.add_mesh(obj, "hero", kind, "HERO")
        if "emissive" in hero_kit.GENERATORS[t][1]:
            self.assign_practical(obj)  # headlights, status lights
        bpy.context.view_layer.update()
        self._settle(obj)
        self._measure_hero(obj)
        self.uses["kits"][hero_kit.KIT] = hero_kit.VERSION

    def _build_character(self, rng):
        """A rigged character hero that walks through the frame or idles."""
        arm, parts, height = character_kit.build_character(self, rng, self.style == "toon")
        for part in parts:
            self.add_mesh(part, "hero", "character", None)  # stays parented to its bone
        arm.parent = self.group("HERO")
        r = self.spec["render"]
        seeded = rng.choice(["walk", "walk", "idle"])
        self.hero_motion = self.spec["hero"].get("motion") or seeded
        frames = (r["frame_start"], r["frame_end"])
        if self.hero_motion == "walk" and character_kit.walk_length(height, frames) > 1.6 * self.clear_radius:
            self.hero_motion = "idle"  # no room to walk at a natural pace
        arm.rotation_euler = (0, 0, rng.uniform(0, math.tau))  # walk heading
        bpy.context.view_layer.update()
        ends = character_kit.animate(arm, rng, frames, self.hero_motion, height)
        if ends:
            self.hero_path = [arm.matrix_world @ e for e in ends]
        self.rig = arm
        self.hero_height = height * 0.55
        self.hero_size = height
        self.uses["kits"][character_kit.KIT] = character_kit.VERSION

    def build_fx(self):
        fx = self.spec.get("fx") or {}
        if fx.get("type") != "collapse" or self.room or self.studio:
            return  # no collapses indoors (debris would tangle with furniture) or on stage
        r = self.spec["render"]
        rng = random.Random(fx.get("seed", self.spec["seed"] * 53 + 11))
        self.fx = fx_kit.build_collapse(self, rng, (r["frame_start"], r["frame_end"]))
        self.uses["kits"][fx_kit.KIT] = fx_kit.VERSION
        # clear props the structure would stand in
        fx_objs = [o for o in self.groups["FX"].children]
        centre = sum((o.location for o in fx_objs), Vector()) / max(len(fx_objs), 1)
        props = self.groups.get("PROPS")
        for obj in list(props.children) if props else []:
            if (obj.location - centre).length < 2.2 + max(obj.dimensions) / 2:
                self.objects = [o for o in self.objects if o["name"] != obj.name]
                bpy.data.objects.remove(obj, do_unlink=True)

    def skeleton_track(self):
        if not getattr(self, "rig", None):
            return None
        r = self.spec["render"]
        return {"bones": list(character_kit.SKELETON), "limbs": character_kit.LIMBS,
                "frames": character_kit.joint_track(self.rig, self.scene, (r["frame_start"], r["frame_end"]))}

    def _measure_hero(self, obj):
        """Camera target height (bounds center) and size, from evaluated bounds."""
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        zs = [(obj.matrix_world @ Vector(c)).z for c in ev.bound_box]
        self.hero_height = (min(zs) + max(zs)) / 2
        self.hero_size = max(obj.dimensions)

    def _settle(self, obj):
        """Rest an object on z=0 using its evaluated (displaced) bounds."""
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        low = min((obj.matrix_world @ Vector(c)).z for c in ev.bound_box)
        obj.location.z -= low
        bpy.context.view_layer.update()

    # ------------------------------------------------------------------ props

    def build_props(self):
        if self.room or self.studio:
            return  # indoors the furniture is the set dressing; on stage, nothing
        props = self.spec["props"]
        rng = random.Random(props["seed"])
        palette = [self.color(rng) for _ in range(4)]
        for i in range(props["count"]):
            angle = rng.uniform(0, math.tau)
            radius = rng.uniform(3.5, 9.0)
            x, y = math.cos(angle) * radius, math.sin(angle) * radius
            if self.hero_path and _dist_to_segment(Vector((x, y, 0)), *self.hero_path) < 1.5:
                continue  # keep the walk path clear
            shape = rng.choice(["crate", "barrel", "ball", "pillar"])
            size = rng.uniform(0.4, 1.2)
            if shape == "crate":
                obj = self._primitive(bpy.ops.mesh.primitive_cube_add, f"prop_crate_{i:02d}", (x, y, size / 2), size=size)
                obj.rotation_euler = (0, 0, rng.uniform(0, math.tau))
                bev = obj.modifiers.new("bevel", "BEVEL")
                bev.width = size * 0.04
                kind = rng.choice(["painted", "concrete"])
            elif shape == "barrel":
                obj = self._primitive(
                    bpy.ops.mesh.primitive_cylinder_add, f"prop_barrel_{i:02d}", (x, y, size * 0.7), radius=size * 0.4, depth=size * 1.4
                )
                kind = rng.choice(["metal", "painted"])
            elif shape == "ball":
                obj = self._primitive(
                    bpy.ops.mesh.primitive_uv_sphere_add, f"prop_ball_{i:02d}", (x, y, size * 0.5), radius=size * 0.5
                )
                kind = rng.choice(["painted", "metal", "glass", "sss"])
            else:
                obj = self._primitive(
                    bpy.ops.mesh.primitive_cylinder_add, f"prop_pillar_{i:02d}", (x, y, size * 1.5), radius=size * 0.2, depth=size * 3, vertices=8
                )
                kind = "concrete"
            if shape in ("barrel", "ball"):
                self._smooth(obj)
            self.add(obj, "prop", kind, self.material(kind, rng.choice(palette)), "PROPS")

    # ------------------------------------------------------------- atmosphere

    def build_atmosphere(self):
        atm = self.spec["atmosphere"]
        if not atm["fog"] or self.studio:
            return
        extent = self.spec["environment"]["extent"]
        box = self._primitive(bpy.ops.mesh.primitive_cube_add, "fog_volume", (0, 0, extent / 2), size=extent * 2.5)
        mat = bpy.data.materials.new("fog")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        vol = nt.nodes.new("ShaderNodeVolumePrincipled")
        vol.inputs["Density"].default_value = atm["fog_density"]
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
        box.data.materials.append(mat)
        box.parent = self.group("ENV")
        box.visible_shadow = False
        for col in list(box.users_collection):  # into the collection the Data layer excludes
            col.objects.unlink(box)
        atmosphere_collection(self.scene).objects.link(box)
        self.objects.append({"name": box.name, "role": "atmosphere", "material": mat.name, "kind": "volume"})

    # ----------------------------------------------------------------- lights

    def build_lights(self):
        lt = self.spec["lighting"]
        rng = random.Random(self.spec["seed"] * 17 + 3)
        elev, sun_color, sun_strength, sky_strength = TIME_OF_DAY[lt["time_of_day"]]
        rot = math.radians(lt["sun_rotation_deg"])
        lights = self.group("LIGHTS")
        if self.studio:
            return self._studio_lights(lt, rng)

        def light(name, ltype, group, energy, color, location=None, rotation=None, **kw):
            data = bpy.data.lights.new(name, ltype)
            data.energy = energy
            data.color = color
            for k, v in kw.items():
                setattr(data, k, v)
            obj = bpy.data.objects.new(name, data)
            obj.visible_camera = False  # lamps light the scene; they aren't props
            self.scene.collection.objects.link(obj)
            if location:
                obj.location = location
            if rotation:
                obj.rotation_euler = rotation
            obj.parent = lights
            assign_lightgroup(obj, group)
            self.lights.append({"name": name, "type": ltype, "group": group, "energy": energy, "color": list(color)})
            return obj

        # Key: the sun.
        light(
            "key_sun", "SUN", "key", sun_strength * lt["key_intensity"], sun_color,
            rotation=(math.radians(90 - elev), 0, rot), angle=math.radians(0.6),
        )
        # Fill: big soft area light roughly opposite the sun. Indoors it is a
        # ceiling softbox (anything outside would be blocked by the shell).
        fill_dir = rot + math.pi
        if self.room:
            light(
                "fill_area", "AREA", "fill", 800 * lt["key_intensity"] * lt["fill_ratio"], (1.0, 0.95, 0.88),
                location=(math.sin(fill_dir) * 2, -math.cos(fill_dir) * 2, self.room["height"] - 0.15),
                size=4.0,
            )
        else:
            light(
                "fill_area", "AREA", "fill", 4000 * lt["key_intensity"] * lt["fill_ratio"], (0.75, 0.85, 1.0),
                location=(math.sin(fill_dir) * 15, -math.cos(fill_dir) * 15, 8),
                rotation=(math.radians(60), 0, fill_dir), size=10.0,
            )
        # Rim: behind the hero relative to camera.
        if lt["rim_intensity"] > 0.05:
            az = math.radians(self.spec["camera"]["azimuth_deg"]) + math.pi
            reach = min(6.0, self.clear_radius - 0.5)
            top = self.hero_height + 3 if not self.room else min(self.hero_height + 3, self.room["height"] - 0.3)
            loc = Vector((math.cos(az) * reach, math.sin(az) * reach, top))
            # A sized source (0.6 m): a near-point 2 kW spot mirrors in glossy
            # floors as a pin-bright hot spot that defocuses into a blob.
            rim = light("rim_spot", "SPOT", "rim", 2500 * lt["rim_intensity"] * (0.5 if self.room else 1.0),
                        (1.0, 0.95, 0.9), location=loc, spot_size=math.radians(45), shadow_soft_size=0.6)
            direction = Vector((0, 0, self.hero_height)) - loc
            rim.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        # Practicals: small warm/cool point lights near the ground.
        # Practicals are always motivated: each sits in a lantern with a
        # visible emissive globe (a bare floating point light reads as an
        # unexplained hot spot). Indoors the interior kit's lamps are the practicals.
        cam = self.spec["camera"]
        cam_az = math.radians(cam["azimuth_deg"])
        keep_out = math.radians(70 + (90 * cam["travel"] if cam["move"] == "orbit" else 0))
        for i in range(0 if self.room else lt["practicals"]):
            while True:  # lanterns stay off the camera's side, out of the lens
                a = rng.uniform(0, math.tau)
                if abs((a - cam_az + math.pi) % math.tau - math.pi) > keep_out:
                    break
            r = rng.uniform(4.0, min(10.0, self.clear_radius))
            hue = rng.choice([0.07, 0.1, 0.55, 0.85])
            color = hsv(hue, 0.6, 1.0)
            h = rng.uniform(1.2, 2.6)
            pos = Vector((math.cos(a) * r, math.sin(a) * r, 0))
            lantern = city_kit.Mesh()
            lantern.cylinder((0, 0, 0), 0.05, h, 0, 8)
            lantern.box((0, 0, h + 0.12), (0.22, 0.22, 0.24), 1)
            obj = lantern.to_object(f"lantern_{i}", [self.material("metal", (0.12, 0.12, 0.12, 1.0)),
                                                     self.material("emissive", color)], self.scene.collection)
            obj.location = pos
            self.add_mesh(obj, "practical", "emissive", "ENV")
            self.assign_practical(obj)
            light(f"practical_{i}", "POINT", "practical", rng.uniform(50, 300), color[:3],
                  location=pos + Vector((0, 0, h + 0.12)), shadow_soft_size=0.1)

        self._world(elev, rot, sky_strength)

    def _studio_lights(self, lt, rng):
        """Stage lighting: area key and fill on the camera side, the rim spot
        behind the subject (in front of the screen), a dim neutral world.
        The screen's own light comes from its material (the "screen" group)."""
        cam_az = math.radians(self.spec["camera"]["azimuth_deg"])
        side = rng.choice([-1, 1])
        target = Vector((0, 0, self.hero_height))

        def area(name, group, az, dist, rise, size, energy, color):
            data = bpy.data.lights.new(name, "AREA")
            data.energy, data.color, data.size = energy, color, size
            obj = bpy.data.objects.new(name, data)
            obj.visible_camera = False
            self.scene.collection.objects.link(obj)
            obj.location = Vector((math.cos(az) * dist, math.sin(az) * dist, self.hero_height + rise))
            obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
            obj.parent = self.group("LIGHTS")
            assign_lightgroup(obj, group)
            self.lights.append({"name": name, "type": "AREA", "group": group, "energy": energy,
                                "color": list(color)})

        # Energies give roughly the outdoor sun's irradiance (about 3 W/m^2)
        # at the subject: area watts ~ 3 * pi * distance^2.
        reach = max(self.hero_size * 2.0, 5.0)
        area("key_area", "key", cam_az + side * math.radians(rng.uniform(25, 65)), reach,
             rng.uniform(1.0, 3.5), rng.uniform(1.5, 3.0), 300 * lt["key_intensity"] * (reach / 5) ** 2,
             (1.0, 0.96, 0.9))
        area("fill_area", "fill", cam_az - side * math.radians(rng.uniform(30, 70)), reach * 1.2,
             rng.uniform(0.0, 1.5), 4.0, 300 * lt["key_intensity"] * lt["fill_ratio"] * (reach / 5) ** 2,
             (0.9, 0.95, 1.0))
        if lt["rim_intensity"] > 0.05:
            az = cam_az + math.pi + rng.uniform(-0.6, 0.6)
            dist = min(self.studio["back"] - 0.8, 4.0)
            data = bpy.data.lights.new("rim_spot", "SPOT")
            data.energy = 500 * lt["rim_intensity"]
            data.spot_size = math.radians(50)
            data.shadow_soft_size = 0.6
            rim = bpy.data.objects.new("rim_spot", data)
            rim.visible_camera = False
            self.scene.collection.objects.link(rim)
            rim.location = Vector((math.cos(az) * dist, math.sin(az) * dist, self.hero_height + 2.5))
            rim.rotation_euler = (target - rim.location).to_track_quat("-Z", "Y").to_euler()
            rim.parent = self.group("LIGHTS")
            assign_lightgroup(rim, "rim")
            self.lights.append({"name": "rim_spot", "type": "SPOT", "group": "rim",
                                "energy": data.energy, "color": [1.0, 1.0, 1.0]})
        world = bpy.data.worlds.new("world")
        self.scene.world = world
        world.use_nodes = True
        nt = world.node_tree
        nt.nodes.clear()
        bg = nt.nodes.new("ShaderNodeBackground")
        out = nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
        bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
        bg.inputs["Strength"].default_value = 0.03  # the dark stage beyond the lights
        world.lightgroup = "env"

    def _world(self, elev, rot, strength):
        world = bpy.data.worlds.new("world")
        self.scene.world = world
        world.use_nodes = True
        nt = world.node_tree
        nt.nodes.clear()
        bg = nt.nodes.new("ShaderNodeBackground")
        bg.inputs["Strength"].default_value = strength * (1.0 if self.style == "toon" else PHYSICAL_SKY_SCALE)
        out = nt.nodes.new("ShaderNodeOutputWorld")
        if self.style == "toon":
            # Flat graphic gradient sky.
            coord = nt.nodes.new("ShaderNodeTexCoord")
            sep = nt.nodes.new("ShaderNodeSeparateXYZ")
            ramp = nt.nodes.new("ShaderNodeValToRGB")
            hue = random.Random(self.spec["seed"]).random()
            ramp.color_ramp.elements[0].color = hsv(hue, 0.25, 0.95)
            ramp.color_ramp.elements[1].color = hsv(hue + 0.05, 0.6, 0.85)
            ramp.color_ramp.interpolation = "CONSTANT"
            ramp.color_ramp.elements.new(0.25).color = hsv(hue + 0.02, 0.4, 0.9)
            nt.links.new(coord.outputs["Generated"], sep.inputs["Vector"])
            nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
            nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
        else:
            sky = nt.nodes.new("ShaderNodeTexSky")
            sky.sky_type = "MULTIPLE_SCATTERING"
            sky.sun_disc = False  # the sun lamp is the key; avoid double-counting
            sky.sun_elevation = math.radians(elev)
            sky.sun_rotation = rot
            nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
        world.lightgroup = "env"

    # ----------------------------------------------------------------- camera

    def build_camera(self):
        cam_spec = self.spec["camera"]
        r = self.spec["render"]
        data = bpy.data.cameras.new("shot_cam")
        data.sensor_width = cam_spec["sensor_mm"]
        data.sensor_fit = "HORIZONTAL"
        data.clip_end = 1000
        cam = bpy.data.objects.new("shot_cam", data)
        self.scene.collection.objects.link(cam)
        self.scene.camera = cam

        target = bpy.data.objects.new("cam_target", None)
        target.location = (0, 0, self.hero_height)
        self.cam_target = target
        if self.hero_path:  # follow a walking character (pan with them)
            a, b = self.hero_path
            f0, f1 = r["frame_start"], r["frame_end"]
            for f in range(f0, f1 + 1):
                p = a.lerp(b, (f - f0) / max(f1 - f0, 1))
                target.location = (p.x, p.y, self.hero_height)
                target.keyframe_insert("location", frame=f)
        self.scene.collection.objects.link(target)
        track = cam.constraints.new("TRACK_TO")
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"

        # Rendered sharp: depth of field is added in comp (ZDefocus) from clean
        # depth, like motion blur. In-camera DOF would blur twice in comp and
        # average depth/IDs/normals across the lens. Focus object and f-stop are
        # still set, so the .blend and the camera track carry the lens.
        data.dof.use_dof = False
        data.dof.focus_object = target
        data.dof.aperture_fstop = cam_spec["fstop"]

        # Camera lives inside the clear zone around the hero; the lens is then
        # chosen so the hero fills `framing` of the frame height.
        res_x, res_y = r["resolution"]
        sensor_h = cam_spec["sensor_mm"] * res_y / res_x
        travel = cam_spec["travel"]
        d_min = self.hero_size * 2.5
        d_max = max(d_min, self.clear_radius / (1 + travel))
        d0 = d_min + (d_max - d_min) * cam_spec["distance_frac"]
        h0 = max(0.5, self.hero_height + cam_spec["height_offset"])
        az0 = math.radians(cam_spec["azimuth_deg"])

        for attempt in range(8):
            data.lens = min(max(d0 * cam_spec["framing"] * sensor_h / self.hero_size, 14.0), 200.0)
            path = self._key_camera(cam, d0, h0, az0)
            if self._camera_clear(cam):
                break
            d0 *= 0.8  # occluded or inside geometry: push in and retry
        self.camera = cam
        self.camera_attempts = attempt + 1
        self._clear_props_near(path)

    def _clear_props_near(self, path, margin=2.5):
        """Remove props the camera would pass through, or that sit on the
        sightline to the hero (long lenses turn those into frame-filling blur)."""
        props = self.groups.get("PROPS")
        if not props:
            return
        target = Vector((0, 0, self.hero_height))
        corridor = max(1.0, self.hero_size * 0.6)

        def in_the_way(obj, p):
            size = max(obj.dimensions) / 2
            if (obj.location - p).length < margin + size:
                return True
            sight = target - p
            t = (obj.location - p).dot(sight) / sight.length_squared
            if not 0.0 < t < 0.85:
                return False
            return (obj.location - (p + sight * t)).length < corridor + size

        removed = set()
        for obj in list(props.children):
            if any(in_the_way(obj, p) for p in path):
                removed.add(obj.name)
                bpy.data.objects.remove(obj, do_unlink=True)
        self.objects = [o for o in self.objects if o["name"] not in removed]

    def _key_camera(self, cam, d0, h0, az0):
        cam_spec = self.spec["camera"]
        r = self.spec["render"]
        travel = cam_spec["travel"]
        move = cam_spec["move"]
        f0, f1 = r["frame_start"], r["frame_end"]
        span = max(f1 - f0, 1)
        cam.animation_data_clear()
        path = []
        for f in range(f0, f1 + 1):
            t = (f - f0) / span
            t = t * t * (3 - 2 * t)  # ease in/out
            d, h, az, lateral = d0, h0, az0, 0.0
            if move == "dolly_in":
                d = d0 * (1 + travel - 2 * travel * t)
            elif move == "orbit":
                az = az0 + math.radians(90) * travel * (2 * t - 1)
            elif move == "truck":
                lateral = d0 * travel * (2 * t - 1)
            elif move == "crane":
                h = h0 + d0 * travel * 1.5 * t
            pos = Vector((math.cos(az) * d, math.sin(az) * d, h))
            side = Vector((-math.sin(az), math.cos(az), 0))
            cam.location = pos + side * lateral
            cam.keyframe_insert("location", frame=f)
            path.append(cam.location.copy())
        return path

    def _camera_clear(self, cam):
        """True if the hero is unobstructed from the camera on every frame."""
        target = Vector((0, 0, self.hero_height))
        for f in range(self.scene.frame_start, self.scene.frame_end + 1):
            self.scene.frame_set(f)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            origin = cam.matrix_world.translation.copy()
            direction = target - origin
            dist = direction.length
            hit, loc, _n, _i, obj, _m = self.scene.ray_cast(depsgraph, origin, direction.normalized(), distance=dist)
            if hit and not obj.name.startswith("hero") and (loc - origin).length < dist - self.hero_size * 0.5:
                return False
        self.scene.frame_set(self.scene.frame_start)
        return True

    def camera_track(self):
        """Per-frame camera world matrix and lens, for meta.json and Nuke."""
        cam = self.camera
        frames = []
        for f in range(self.scene.frame_start, self.scene.frame_end + 1):
            self.scene.frame_set(f)
            m = cam.matrix_world
            frames.append({
                "frame": f,
                "matrix_world": [list(row) for row in m],
                "focal_mm": cam.data.lens,
                "focus_distance": (m.translation - self.cam_target.matrix_world.translation).length,
            })
        self.scene.frame_set(self.scene.frame_start)
        return {
            "sensor_mm": cam.data.sensor_width,
            "focal_mm": cam.data.lens,
            "placement_attempts": self.camera_attempts,
            "fstop": cam.data.dof.aperture_fstop,
            "convention": "Blender Z-up, camera looks down -Z",
            "frames": frames,
        }

    def build(self):
        self.build_environment()
        self.build_hero()
        self.build_props()
        self.build_lights()
        self.build_camera()  # before the fog box, which would block ray casts
        self.build_fx()
        self.build_atmosphere()
        if self.studio:
            stage_kit.build_stage(self, random.Random(self.spec["environment"]["seed"] + 1))
            stage_kit.move_subject(self)
            setup_keying(self.scene, stage_kit.SCREEN_COLLECTION, stage_kit.SUBJECT_COLLECTION)
