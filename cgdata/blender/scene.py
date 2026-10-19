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
from materials import hsv, make_material
from passes import assign_lightgroup

# Radius around the hero kept free of environment geometry for the camera.
CLEAR_RADIUS = 18.0

# Blender 5.2's multiple-scattering sky is far brighter per unit strength
# than a sun lamp in W/m^2 (strength 0.3 outshone a 2.2 sun in a sun-only vs
# sky-only test), so the photoreal sky is scaled down to sit under the key.
PHYSICAL_SKY_SCALE = 0.2

PASS_INDEX = {"hero": 1, "prop": 2, "environment": 3, "ground": 4, "practical": 5}

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
        """Register a kit object that already carries its own material slots."""
        obj.pass_index = PASS_INDEX[role]
        obj.parent = self.group(parent)
        self.objects.append({"name": obj.name, "role": role, "kind": kind,
                             "material": [m.name for m in obj.data.materials]})
        return obj

    def assign_practical(self, obj):
        """Emission on this object (lit windows, lamp heads) is a practical light."""
        assign_lightgroup(obj, "practical")

    def point_light(self, name, location, energy, color, group="practical"):
        data = bpy.data.lights.new(name, "POINT")
        data.energy = energy
        data.color = color
        data.shadow_soft_size = 0.15
        obj = bpy.data.objects.new(name, data)
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

        ground_kind = "ground"
        ground_color = self.color(rng, hue=0.08)
        ground = self._primitive(bpy.ops.mesh.primitive_plane_add, "ground", (0, 0, 0), size=extent * 4)
        self._displace(ground, 1.5, 6.0, env["seed"], levels=5)
        self.add(ground, "ground", ground_kind, self.material(ground_kind, ground_color), "ENV")

        self._canyon(rng, extent, env["density"])

    def _canyon(self, rng, extent, density):
        count = int(30 * density)
        for i in range(count):
            angle = rng.uniform(0, math.tau)
            radius = rng.uniform(CLEAR_RADIUS + 3.0, extent)
            loc = (math.cos(angle) * radius, math.sin(angle) * radius, 0)
            h = rng.uniform(3.0, 18.0)
            rock = self._primitive(
                bpy.ops.mesh.primitive_ico_sphere_add, f"rock_{i:03d}", loc, subdivisions=2, radius=1.0
            )
            rock.scale = (rng.uniform(1.5, 4.0), rng.uniform(1.5, 4.0), h / 2)
            rock.rotation_euler = (0, 0, rng.uniform(0, math.tau))
            self._displace(rock, 0.6, 0.8, rng.randrange(1 << 20))
            self._smooth(rock)
            color = self.color(rng, hue=rng.uniform(0.02, 0.1))
            self.add(rock, "environment", "rock", self.material("rock", color), "ENV")

    # ------------------------------------------------------------------- hero

    def build_hero(self):
        hero = self.spec["hero"]
        rng = random.Random(self.spec["seed"] * 31 + 7)
        s = hero["scale"]
        color = self.color(rng, hue=hero["hue"])
        t = hero["type"]
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
        self.hero_height = obj.location.z
        self.hero_size = max(obj.dimensions)

    # ------------------------------------------------------------------ props

    def build_props(self):
        props = self.spec["props"]
        rng = random.Random(props["seed"])
        palette = [self.color(rng) for _ in range(4)]
        for i in range(props["count"]):
            angle = rng.uniform(0, math.tau)
            radius = rng.uniform(3.5, 9.0)
            x, y = math.cos(angle) * radius, math.sin(angle) * radius
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
        if not atm["fog"]:
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
        self.objects.append({"name": box.name, "role": "atmosphere", "material": mat.name, "kind": "volume"})

    # ----------------------------------------------------------------- lights

    def build_lights(self):
        lt = self.spec["lighting"]
        rng = random.Random(self.spec["seed"] * 17 + 3)
        elev, sun_color, sun_strength, sky_strength = TIME_OF_DAY[lt["time_of_day"]]
        rot = math.radians(lt["sun_rotation_deg"])
        lights = self.group("LIGHTS")

        def light(name, ltype, group, energy, color, location=None, rotation=None, **kw):
            data = bpy.data.lights.new(name, ltype)
            data.energy = energy
            data.color = color
            for k, v in kw.items():
                setattr(data, k, v)
            obj = bpy.data.objects.new(name, data)
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
        # Fill: big soft area light roughly opposite the sun.
        fill_dir = rot + math.pi
        light(
            "fill_area", "AREA", "fill", 4000 * lt["key_intensity"] * lt["fill_ratio"], (0.75, 0.85, 1.0),
            location=(math.sin(fill_dir) * 15, -math.cos(fill_dir) * 15, 8),
            rotation=(math.radians(60), 0, fill_dir), size=10.0,
        )
        # Rim: behind the hero relative to camera.
        if lt["rim_intensity"] > 0.05:
            az = math.radians(self.spec["camera"]["azimuth_deg"]) + math.pi
            loc = Vector((math.cos(az) * 6, math.sin(az) * 6, self.hero_height + 3))
            rim = light("rim_spot", "SPOT", "rim", 2500 * lt["rim_intensity"], (1.0, 0.95, 0.9), location=loc,
                        spot_size=math.radians(45))
            direction = Vector((0, 0, self.hero_height)) - loc
            rim.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        # Practicals: small warm/cool point lights near the ground.
        for i in range(lt["practicals"]):
            a = rng.uniform(0, math.tau)
            r = rng.uniform(3.0, 10.0)
            hue = rng.choice([0.07, 0.1, 0.55, 0.85])
            light(f"practical_{i}", "POINT", "practical", rng.uniform(50, 300), hsv(hue, 0.6, 1.0)[:3],
                  location=(math.cos(a) * r, math.sin(a) * r, rng.uniform(0.5, 3.0)), shadow_soft_size=0.1)

        self._world(elev, rot, sky_strength)

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
        self.scene.collection.objects.link(target)
        track = cam.constraints.new("TRACK_TO")
        track.target = target
        track.track_axis = "TRACK_NEGATIVE_Z"
        track.up_axis = "UP_Y"

        data.dof.use_dof = True
        data.dof.focus_object = target
        data.dof.aperture_fstop = cam_spec["fstop"]

        # Camera lives inside the clear zone around the hero; the lens is then
        # chosen so the hero fills `framing` of the frame height.
        res_x, res_y = r["resolution"]
        sensor_h = cam_spec["sensor_mm"] * res_y / res_x
        travel = cam_spec["travel"]
        d_min = self.hero_size * 2.5
        d_max = max(d_min, CLEAR_RADIUS / (1 + travel))
        d0 = d_min + (d_max - d_min) * cam_spec["distance_frac"]
        h0 = max(0.5, self.hero_height + cam_spec["height_offset"])
        az0 = math.radians(cam_spec["azimuth_deg"])

        for attempt in range(8):
            data.lens = min(max(d0 * cam_spec["framing"] * sensor_h / self.hero_size, 14.0), 200.0)
            self._key_camera(cam, d0, h0, az0)
            if self._camera_clear(cam):
                break
            d0 *= 0.8  # occluded or inside geometry: push in and retry
        self.camera = cam
        self.camera_attempts = attempt + 1

    def _key_camera(self, cam, d0, h0, az0):
        cam_spec = self.spec["camera"]
        r = self.spec["render"]
        travel = cam_spec["travel"]
        move = cam_spec["move"]
        f0, f1 = r["frame_start"], r["frame_end"]
        span = max(f1 - f0, 1)
        cam.animation_data_clear()
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
                "focus_distance": (m.translation - Vector((0, 0, self.hero_height))).length,
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
        self.build_atmosphere()
