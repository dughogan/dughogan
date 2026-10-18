"""Render pass configuration: every Cycles AOV, light groups, shader AOVs.

Passes are written by a compositor File Output node as one multilayer EXR per
frame (ZIP, lossless): Blender 5.x's direct render output only saves Combined.
The regular render output becomes an sRGB PNG preview of the beauty.

Cycles has no separate subsurface passes since 4.0 (SSS is part of Diffuse),
and Shadow is EEVEE-only; those toggles are set anyway and simply produce
nothing in Cycles.
"""

import bpy

from materials import SHADER_AOVS

LIGHT_GROUPS = ["key", "fill", "rim", "practical", "env"]

VIEW_LAYER_PASSES = [
    "use_pass_combined",
    "use_pass_z",
    "use_pass_mist",
    "use_pass_normal",
    "use_pass_position",
    "use_pass_vector",
    "use_pass_uv",
    "use_pass_object_index",
    "use_pass_material_index",
    "use_pass_diffuse_direct",
    "use_pass_diffuse_indirect",
    "use_pass_diffuse_color",
    "use_pass_glossy_direct",
    "use_pass_glossy_indirect",
    "use_pass_glossy_color",
    "use_pass_transmission_direct",
    "use_pass_transmission_indirect",
    "use_pass_transmission_color",
    "use_pass_subsurface_direct",
    "use_pass_subsurface_indirect",
    "use_pass_subsurface_color",
    "use_pass_emit",
    "use_pass_environment",
    "use_pass_ambient_occlusion",
    "use_pass_shadow",
    "use_pass_cryptomatte_object",
    "use_pass_cryptomatte_material",
    "use_pass_cryptomatte_asset",
]

CYCLES_LAYER_PASSES = ["use_pass_volume_direct", "use_pass_volume_indirect"]


def configure(scene, spec):
    r = spec["render"]
    scene.render.engine = "CYCLES"
    cy = scene.cycles
    cy.samples = r["samples"]
    cy.use_adaptive_sampling = True
    cy.use_denoising = r["denoise_combined"]
    cy.max_bounces = 12
    cy.transparent_max_bounces = 16
    # Motion blur off: the Vector pass is only valid without it, and blur is
    # added back in comp with VectorBlur.
    scene.render.use_motion_blur = False

    scene.render.resolution_x, scene.render.resolution_y = r["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.fps = r["fps"]
    scene.frame_start = r["frame_start"]
    scene.frame_end = r["frame_end"]

    vl = scene.view_layers[0]
    vl.name = "ViewLayer"
    for attr in VIEW_LAYER_PASSES:
        setattr(vl, attr, True)
    for attr in CYCLES_LAYER_PASSES:
        setattr(vl.cycles, attr, True)
    vl.cycles.denoising_store_passes = True
    vl.pass_cryptomatte_depth = 6
    vl.pass_alpha_threshold = 0.0  # Z/Normal/etc. for every sample, not just opaque

    for name, aov_type in SHADER_AOVS:
        aov = vl.aovs.add()
        aov.name = name
        aov.type = aov_type

    for name in LIGHT_GROUPS:
        vl.lightgroups.add(name=name)

    img = scene.render.image_settings
    img.media_type = "IMAGE"
    img.file_format = "PNG"
    img.color_depth = "8"
    scene.render.use_compositing = True
    scene.render.compositor_device = "CPU"  # no GPU context needed on farm nodes
    scene.render.use_sequencer = False
    scene.render.film_transparent = False

    # Scene-linear output, no view transform baked into anything: the EXRs
    # are Linear Rec.709 (Blender's working space). Recorded in meta.json.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"


# Render Layers socket name -> EXR layer name. Follows Blender's own short
# pass names so Nuke/Cryptomatte tools recognize them; anything not listed
# (shader AOVs, Combined_<lightgroup>, CryptoXX) keeps its socket name.
LAYER_NAMES = {
    "Image": "Combined",
    "Alpha": None,  # already Combined.A
    "Diffuse Direct": "DiffDir",
    "Diffuse Indirect": "DiffInd",
    "Diffuse Color": "DiffCol",
    "Glossy Direct": "GlossDir",
    "Glossy Indirect": "GlossInd",
    "Glossy Color": "GlossCol",
    "Transmission Direct": "TransDir",
    "Transmission Indirect": "TransInd",
    "Transmission Color": "TransCol",
    "Volume Direct": "VolumeDir",
    "Volume Indirect": "VolumeInd",
    "Emission": "Emit",
    "Environment": "Env",
    "Ambient Occlusion": "AO",
    "Object Index": "IndexOB",
    "Material Index": "IndexMA",
    "Denoising Albedo": "Denoising_Albedo",
    "Denoising Specular Albedo": "Denoising_SpecAlbedo",
    "Denoising Normal": "Denoising_Normal",
    "Denoising Roughness": "Denoising_Roughness",
    "Denoising Depth": "Denoising_Depth",
}

SOCKET_TYPES = {"RGBA": "RGBA", "VECTOR": "VECTOR", "VALUE": "FLOAT"}

# Layers that must stay full float: geometry, vectors, IDs and Cryptomatte
# hashes break at half precision. Everything else (light passes, colors,
# light groups) is written half float to roughly halve storage.
DATA_LAYERS = {"Depth", "Mist", "Position", "Normal", "Vector", "UV", "IndexOB", "IndexMA",
               "Denoising_Normal", "Denoising_Depth"}


def _is_data(name):
    return name in DATA_LAYERS or name.startswith("Crypto")


def _file_output(tree, directory, file_name, depth, x):
    out = tree.nodes.new("CompositorNodeOutputFile")
    out.location = (x, 0)
    out.directory = str(directory)
    out.file_name = file_name
    fmt = out.format
    fmt.media_type = "MULTI_LAYER_IMAGE"
    fmt.file_format = "OPEN_EXR_MULTILAYER"
    fmt.color_depth = depth
    fmt.exr_codec = "ZIP"
    return out


def add_exr_outputs(scene, directory, shot_id):
    """Wire every enabled render pass into two multilayer EXRs per frame:
    <shot_id>_light.####.exr (half) and <shot_id>_data.####.exr (float)."""
    tree = bpy.data.node_groups.new("dataset_output", "CompositorNodeTree")
    scene.compositing_node_group = tree
    layers = tree.nodes.new("CompositorNodeRLayers")
    layers.scene = scene
    light = _file_output(tree, directory, f"{shot_id}_light.", "16", 500)
    data = _file_output(tree, directory, f"{shot_id}_data.", "32", 800)

    written = {"light": [], "data": []}
    for sock in layers.outputs:
        if not sock.enabled:
            continue
        name = LAYER_NAMES.get(sock.name, sock.name)
        if name is None:
            continue
        kind = "data" if _is_data(name) else "light"
        out = data if kind == "data" else light
        # Vector holds 4 components (prev xy, next xy); a VECTOR item drops one.
        socket_type = "RGBA" if name == "Vector" else SOCKET_TYPES.get(sock.type, "RGBA")
        item = out.file_output_items.new(socket_type, name)
        tree.links.new(sock, out.inputs[item.name])
        written[kind].append(name)

    # Group output drives the regular render output (the PNG preview).
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    group_out = tree.nodes.new("NodeGroupOutput")
    group_out.location = (500, 300)
    tree.links.new(layers.outputs["Image"], group_out.inputs["Image"])
    return written


def assign_lightgroup(obj, group):
    if group not in LIGHT_GROUPS:
        raise ValueError(f"unknown light group {group!r}")
    obj.lightgroup = group
