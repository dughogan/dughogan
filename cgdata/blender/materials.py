"""Procedural material library, photoreal and toon variants.

Every material writes three shader AOVs (base_color, roughness, metallic) so
the dataset carries material ground truth alongside Cycles' lighting passes.
All materials are fully procedural: no image textures, so no third-party
licensing questions and nothing to pack.
"""

import colorsys

import bpy

# Shader AOVs registered on the view layer by passes.py; names must match.
SHADER_AOVS = [("base_color", "COLOR"), ("roughness", "VALUE"), ("metallic", "VALUE")]

KINDS = ["painted", "concrete", "rock", "metal", "glass", "sss", "emissive", "ground",
         "brick", "window", "window_lit", "asphalt", "bark", "foliage", "wood", "fabric"]


def hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (r, g, b, 1.0)


def _new_material(name):
    mat = bpy.data.materials.new(name)
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    return mat, nt, out


def _aov_outputs(nt, color_socket, roughness, metallic):
    """Write material ground truth to the shader AOVs."""
    for name, value in (("base_color", color_socket), ("roughness", roughness), ("metallic", metallic)):
        node = nt.nodes.new("ShaderNodeOutputAOV")
        node.aov_name = name
        node.location = (600, -200 - 120 * len(nt.nodes))
        sock = node.inputs["Color"] if name == "base_color" else node.inputs["Value"]
        if isinstance(value, bpy.types.NodeSocket):
            nt.links.new(value, sock)
        elif name == "base_color":
            sock.default_value = value
        else:
            sock.default_value = value


def _noise_color(nt, color, variation, scale):
    """Base color with low-frequency procedural variation (dirt, wear)."""
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = 6.0
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = variation
    mix.inputs["A"].default_value = color
    nt.links.new(tex.outputs["Color"], mix.inputs["B"])
    return mix.outputs["Result"]


def _brick_color(nt, color):
    """Running-bond brick in meters, driven by the facade UVs the kits write."""
    uv = nt.nodes.new("ShaderNodeTexCoord")
    tex = nt.nodes.new("ShaderNodeTexBrick")
    tex.offset = 0.5
    tex.inputs["Color1"].default_value = color
    tex.inputs["Color2"].default_value = tuple(c * 0.78 for c in color[:3]) + (1.0,)
    tex.inputs["Mortar"].default_value = (0.55, 0.53, 0.5, 1.0)
    tex.inputs["Scale"].default_value = 1.0
    tex.inputs["Mortar Size"].default_value = 0.008
    tex.inputs["Brick Width"].default_value = 0.24
    tex.inputs["Row Height"].default_value = 0.075
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    return tex.outputs["Color"]


def _wood_color(nt, color):
    """Plank grain: stretched wave bands broken up by noise."""
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0, 12.0, 1.0)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 2.0
    wave.inputs["Distortion"].default_value = 6.0
    wave.inputs["Detail"].default_value = 3.0
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = color
    mix.inputs["B"].default_value = tuple(c * 0.6 for c in color[:3]) + (1.0,)
    nt.links.new(wave.outputs["Fac"], mix.inputs["Factor"])
    return mix.outputs["Result"]


def _photoreal(name, kind, color):
    mat, nt, out = _new_material(name)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    params = {
        "painted": dict(rough=0.45, metal=0.0, var=0.25, scale=4.0),
        "concrete": dict(rough=0.85, metal=0.0, var=0.5, scale=8.0),
        "rock": dict(rough=0.9, metal=0.0, var=0.6, scale=3.0),
        "metal": dict(rough=0.2, metal=1.0, var=0.15, scale=12.0),
        "ground": dict(rough=0.95, metal=0.0, var=0.5, scale=1.5),
        "glass": dict(rough=0.02, metal=0.0, var=0.0, scale=1.0),
        "sss": dict(rough=0.35, metal=0.0, var=0.1, scale=2.0),
        "emissive": dict(rough=0.5, metal=0.0, var=0.0, scale=1.0),
        "brick": dict(rough=0.85, metal=0.0, var=0.0, scale=1.0),
        "window": dict(rough=0.04, metal=0.0, var=0.0, scale=1.0),
        "window_lit": dict(rough=0.04, metal=0.0, var=0.0, scale=1.0),
        "asphalt": dict(rough=0.9, metal=0.0, var=0.45, scale=25.0),
        "bark": dict(rough=0.9, metal=0.0, var=0.55, scale=9.0),
        "foliage": dict(rough=0.55, metal=0.0, var=0.35, scale=3.0),
        "wood": dict(rough=0.45, metal=0.0, var=0.0, scale=1.0),
        "fabric": dict(rough=0.95, metal=0.0, var=0.2, scale=40.0),
    }[kind]

    if kind == "brick":
        base = _brick_color(nt, color)
    elif kind == "wood":
        base = _wood_color(nt, color)
    elif kind in ("window", "window_lit"):
        base = (0.02, 0.025, 0.03, 1.0)  # dark glazing; reflections do the work
    elif params["var"]:
        base = _noise_color(nt, color, params["var"], params["scale"])
    else:
        base = color
    if isinstance(base, bpy.types.NodeSocket):
        nt.links.new(base, bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Roughness"].default_value = params["rough"]
    bsdf.inputs["Metallic"].default_value = params["metal"]

    if kind == "glass":
        bsdf.inputs["Transmission Weight"].default_value = 1.0
        bsdf.inputs["IOR"].default_value = 1.45
    elif kind == "sss":
        bsdf.inputs["Subsurface Weight"].default_value = 1.0
        bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.4, 0.25)
        bsdf.inputs["Subsurface Scale"].default_value = 0.3
    elif kind == "emissive":
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 12.0
    elif kind == "fabric":
        bsdf.inputs["Sheen Weight"].default_value = 0.6
    elif kind == "foliage":
        # thin leaves let light through: a little subsurface keeps them from reading as plastic
        bsdf.inputs["Subsurface Weight"].default_value = 0.15
        bsdf.inputs["Subsurface Radius"].default_value = (0.3, 0.6, 0.2)
        bsdf.inputs["Subsurface Scale"].default_value = 0.05
    elif kind == "window_lit":
        # An interior light seen through glazing.
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 1.2

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    _aov_outputs(nt, base, params["rough"], params["metal"])
    return mat


def _toon(name, kind, color):
    """Cel-shaded look built from Cycles-native nodes.

    Shader-to-RGB is EEVEE-only, so the toon look uses Toon BSDFs. This keeps
    every Cycles lighting pass valid for the toon half of the dataset.
    """
    mat, nt, out = _new_material(name)
    if kind in ("emissive", "window_lit"):
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = color
        em.inputs["Strength"].default_value = 8.0 if kind == "emissive" else 1.0
        nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
        _aov_outputs(nt, color, 1.0, 0.0)
        return mat

    if kind == "glass":
        glass = nt.nodes.new("ShaderNodeBsdfGlass")
        glass.inputs["Color"].default_value = color
        glass.inputs["Roughness"].default_value = 0.0
        nt.links.new(glass.outputs["BSDF"], out.inputs["Surface"])
        _aov_outputs(nt, color, 0.0, 0.0)
        return mat

    if kind == "window":
        color = (0.08, 0.12, 0.2, 1.0)  # graphic dark-blue glazing
    diffuse = nt.nodes.new("ShaderNodeBsdfToon")
    diffuse.component = "DIFFUSE"
    diffuse.inputs["Color"].default_value = color
    diffuse.inputs["Size"].default_value = 0.5
    diffuse.inputs["Smooth"].default_value = 0.02

    gloss = nt.nodes.new("ShaderNodeBsdfToon")
    gloss.component = "GLOSSY"
    gloss.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    gloss.inputs["Size"].default_value = 0.15 if kind == "metal" else 0.05
    gloss.inputs["Smooth"].default_value = 0.0

    mix = nt.nodes.new("ShaderNodeMixShader")
    # Matte surfaces stay matte in toon: a crisp toon highlight on floors and
    # walls mirrors every strong light as a hard hot spot.
    mix.inputs["Fac"].default_value = {"metal": 0.35, "window": 0.5}.get(kind, 0.0)
    nt.links.new(diffuse.outputs["BSDF"], mix.inputs[1])
    nt.links.new(gloss.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    _aov_outputs(nt, color, 0.5, 1.0 if kind == "metal" else 0.0)
    return mat


def make_material(name, style, kind, color):
    if kind not in KINDS:
        raise ValueError(f"unknown material kind {kind!r}")
    builder = _toon if style == "toon" else _photoreal
    return builder(name, kind, color)
