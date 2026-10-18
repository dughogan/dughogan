"""Build, save and render the finishing comp for a dataset shot in Nuke.

    nuke -t cgdata/nuke/build_comp.py LIBRARY/cg/CG_000001 [--no-render]

Writes into the shot directory:
    comp/<shot_id>_comp.nk               the generated Nuke script
    comp/<shot_id>_comp.json             the finishing parameters used
    final/<shot_id>_final.####.exr       scene-linear final comp
    final/<shot_id>_final.####.png       sRGB display version

Comp graph:
    light groups -> per-group Grade -> sum (relit beauty)
      -> depth haze -> ZDefocus -> VectorBlur -> Glow
      -> chromatic aberration -> vignette -> grade -> grain -> Write

Layer and channel names are discovered from the Read nodes at runtime, so the
script works however a given Nuke version names multi-part EXR layers.
Knobs are set through _set(), which warns instead of failing when a knob does
not exist in the running Nuke version.
"""

import json
import os
import sys

import nuke

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from cgdata.comp_params import LIGHT_GROUPS, make_comp_params  # noqa: E402

WARNINGS = []


def _set(node, knob, value):
    k = node.knob(knob)
    if k is None:
        WARNINGS.append("%s: no knob %r" % (node.Class(), knob))
        return
    try:
        k.setValue(value)
    except Exception as e:  # knob types vary across Nuke versions
        WARNINGS.append("%s.%s: %s" % (node.Class(), knob, e))


def _create(cls, inputs=(), **knobs):
    # nuke.nodes.* does not auto-connect to the selection like createNode does.
    node = getattr(nuke.nodes, cls)()
    for i, n in enumerate(inputs):
        node.setInput(i, n)
    for k, v in knobs.items():
        _set(node, k, v)
    return node


CHANNEL_ORDER = ["red", "green", "blue", "alpha", "r", "g", "b", "a", "x", "y", "z", "w", "v"]


def _layer_channels(read, name):
    """Channels of the EXR layer called `name`, in component order.

    Exact layer-name matches win; otherwise accept a prefixed form such as
    "ViewLayer.Depth" or "ViewLayer_Depth" (naming varies by Nuke version).
    """
    want = name.lower()
    by_layer = {}
    for c in read.channels():
        by_layer.setdefault(c.rsplit(".", 1)[0], []).append(c)
    exact = [l for l in by_layer if l.lower() == want]
    prefixed = [l for l in by_layer
                if (l.lower().endswith("." + want) or l.lower().endswith("_" + want))
                and not l.lower().startswith("denoising")]
    layers = exact or prefixed
    if not layers and want == "combined":
        layers = ["rgba"] if "rgba" in by_layer else []
    if not layers:
        return []
    chans = by_layer[layers[0]]

    def key(c):
        comp = c.rsplit(".", 1)[1].lower()
        return CHANNEL_ORDER.index(comp) if comp in CHANNEL_ORDER else 99
    return sorted(chans, key=key)


def _shuffle_to_rgb(read, layer):
    """Pull an EXR layer into rgb via a Copy node."""
    chans = _layer_channels(read, layer)
    if len(chans) < 3:
        raise RuntimeError("layer %r not found in %s (have: %s)"
                           % (layer, read["file"].value(), sorted({c.rsplit('.', 1)[0] for c in read.channels()})))
    node = _create("Copy", [read, read])
    for i, (src, dst) in enumerate(zip(chans[:3], ["rgba.red", "rgba.green", "rgba.blue"])):
        _set(node, "from%d" % i, src)
        _set(node, "to%d" % i, dst)
    return node


def _copy_channels(dst_stream, read, layer, targets):
    """Copy a data layer's channels into channels of the main stream
    (Copy: input 0 = B, the stream; input 1 = A, the source)."""
    chans = _layer_channels(read, layer)
    if len(chans) < len(targets):
        WARNINGS.append("data layer %r missing or short (%d channels)" % (layer, len(chans)))
        return dst_stream
    node = _create("Copy", [dst_stream, read])
    for i, (src, dst) in enumerate(zip(chans, targets)):
        _set(node, "from%d" % i, src)
        _set(node, "to%d" % i, dst)
    return node


def build(shot_dir, render=True):
    spec = json.load(open(os.path.join(shot_dir, "spec.json")))
    scene = json.load(open(os.path.join(shot_dir, "scene.json")))
    shot_id = spec["shot_id"]
    r = spec["render"]
    first, last = r["frame_start"], r["frame_end"]
    params = make_comp_params(spec)

    nuke.scriptClear()
    root = nuke.root()
    _set(root, "first_frame", first)
    _set(root, "last_frame", last)
    _set(root, "fps", r["fps"])
    w, h = r["resolution"]
    fmt_name = "cgdata_%dx%d" % (w, h)
    nuke.addFormat("%d %d 1.0 %s" % (w, h, fmt_name))
    _set(root, "format", fmt_name)

    renders = os.path.join(os.path.abspath(shot_dir), "renders")
    light = _create("Read", file=os.path.join(renders, "%s_light.####.exr" % shot_id).replace("\\", "/"),
                    first=first, last=last, origfirst=first, origlast=last, raw=True)
    light.setName("Read_light")
    data = _create("Read", file=os.path.join(renders, "%s_data.####.exr" % shot_id).replace("\\", "/"),
                   first=first, last=last, origfirst=first, origlast=last, raw=True)
    data.setName("Read_data")

    # --- relight: sum of graded light groups --------------------------------
    stream = None
    for group in LIGHT_GROUPS:
        layer = "Combined_" + group
        if not _layer_channels(light, layer):
            WARNINGS.append("light group %r not in render" % group)
            continue
        lg = _shuffle_to_rgb(light, layer)
        g = params["light_group_gain"][group]
        grade = _create("Grade", [lg], white=[g, g, g, 1.0])
        grade.setName("LG_%s" % group)
        stream = grade if stream is None else _create("Merge2", [stream, grade], operation="plus", output="rgb")
    if stream is None:  # no light groups: fall back to Combined
        stream = _shuffle_to_rgb(light, "Combined")

    # Bring data passes into the stream for defocus / motion blur / haze.
    stream = _copy_channels(stream, data, "Depth", ["depth.Z"])
    # Blender Vector = (to previous x, y, to next x, y) in pixels; verify the
    # sign convention against a known move before relying on it at scale.
    stream = _copy_channels(stream, data, "Vector", ["backward.u", "backward.v", "forward.u", "forward.v"])

    # --- depth haze ---------------------------------------------------------
    hz = params["haze"]
    if hz["enabled"]:
        fr, fg, fb = hz["color"]
        haze = _create("Expression", [stream])
        _set(haze, "temp_name0", "f")
        _set(haze, "temp_expr0", "1 - exp(-depth.Z * %g)" % hz["density"])
        _set(haze, "expr0", "r * (1 - f) + %g * f" % fr)
        _set(haze, "expr1", "g * (1 - f) + %g * f" % fg)
        _set(haze, "expr2", "b * (1 - f) + %g * f" % fb)
        haze.setName("DepthHaze")
        stream = haze

    # --- lens: defocus, motion blur, glow ------------------------------------
    focus = scene["camera"]["frames"][len(scene["camera"]["frames"]) // 2]["focus_distance"]
    df = params["defocus"]
    if df["enabled"]:
        zd = _create("ZDefocus2", [stream], math="depth", size=df["size"], max_size=df["max_size"])
        _set(zd, "depth_channel", "depth.Z")
        _set(zd, "focus_plane", focus)
        zd.setName("ZDefocus_lens")
        stream = zd

    mb = params["motion_blur"]
    if mb["enabled"]:
        vb = _create("VectorBlur2", [stream], uv="forward", scale=mb["shutter"])
        vb.setName("VectorBlur_shutter")
        stream = vb

    gl = params["glow"]
    if gl["enabled"]:
        stream = _create("Glow2", [stream], tolerance=gl["tolerance"], brightness=gl["brightness"], size=gl["size"])

    # --- chromatic aberration: scale red out, blue in ------------------------
    ca = params["chromatic_aberration"]
    if ca["enabled"]:
        center = [w / 2.0, h / 2.0]
        red = _create("Transform", [stream], scale=1 + ca["amount"], center=center, filter="Cubic")
        blue = _create("Transform", [stream], scale=1 - ca["amount"], center=center, filter="Cubic")
        cr = _create("Copy", [stream, red], from0="rgba.red", to0="rgba.red")
        stream = _create("Copy", [cr, blue], from0="rgba.blue", to0="rgba.blue")
        stream.setName("ChromaticAberration")

    # --- vignette -----------------------------------------------------------
    v = params["vignette"]["amount"]
    if v > 0:
        vig = _create("Expression", [stream])
        _set(vig, "temp_name0", "d")
        _set(vig, "temp_expr0", "1 - %g * pow(hypot((x - width/2) / (width/2), (y - height/2) / (height/2)) / 1.4142, 2)" % v)
        for i, c in enumerate("rgb"):
            _set(vig, "expr%d" % i, "%s * d" % c)
        vig.setName("Vignette")
        stream = vig

    # --- grade --------------------------------------------------------------
    gr = params["grade"]
    stream = _create("ColorCorrect", [stream], saturation=gr["saturation"], contrast=gr["contrast"],
                     gamma=gr["gamma"], gain=gr["gain"], offset=gr["lift"])
    stream.setName("FinalGrade")

    # --- film grain (photoreal only) ----------------------------------------
    gn = params["grain"]
    if gn["enabled"]:
        grain = _create("Grain2", [stream])
        _set(grain, "intensity_r", 0.03 * gn["intensity"])
        _set(grain, "intensity_g", 0.03 * gn["intensity"])
        _set(grain, "intensity_b", 0.035 * gn["intensity"])
        _set(grain, "size_r", 2.0 * gn["size"])
        _set(grain, "size_g", 2.0 * gn["size"])
        _set(grain, "size_b", 2.5 * gn["size"])
        stream = grain

    # --- outputs ------------------------------------------------------------
    final_dir = os.path.join(os.path.abspath(shot_dir), "final")
    comp_dir = os.path.join(os.path.abspath(shot_dir), "comp")
    for d in (final_dir, comp_dir):
        if not os.path.isdir(d):
            os.makedirs(d)
    rgb_only = _create("Remove", [stream], operation="keep", channels="rgba")
    w_exr = _create("Write", [rgb_only], file=os.path.join(final_dir, "%s_final.####.exr" % shot_id).replace("\\", "/"),
                    file_type="exr", raw=True, compression="Zip (1 scanline)", datatype="16 bit half",
                    create_directories=True)
    w_exr.setName("Write_final_exr")
    w_png = _create("Write", [rgb_only], file=os.path.join(final_dir, "%s_final.####.png" % shot_id).replace("\\", "/"),
                    file_type="png", create_directories=True)
    w_png.setName("Write_final_png")

    nk_path = os.path.join(comp_dir, "%s_comp.nk" % shot_id).replace("\\", "/")
    nuke.scriptSaveAs(nk_path, overwrite=1)
    with open(os.path.join(comp_dir, "%s_comp.json" % shot_id), "w") as f:
        json.dump({"params": params, "nuke_version": nuke.NUKE_VERSION_STRING, "warnings": WARNINGS}, f, indent=2)

    if render:
        nuke.executeMultiple([w_exr, w_png], ((first, last, 1),))
    for msg in WARNINGS:
        print("build_comp warning: " + msg)
    print("build_comp: wrote " + nk_path)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    build(args[0], render="--no-render" not in sys.argv)


if __name__ == "__main__":
    main()
