"""Export clips as LTX-ready videos and IC-LoRA pair manifests.

    python -m cgdata.export LIBRARY [--shots CG_000001 ...] [--workers 4]

Per clip, into LIBRARY/export/<id>/ (H.264, 24 fps, the render's own /32
resolution and 8n+1 frame count):
    <id>_target.mp4        finished comp if rendered, else the beauty preview
    <id>_beauty.mp4        raw render (AgX preview)
    <id>_depth.mp4         inverse depth, normalized per clip (near = bright)
    <id>_normal.mp4        camera-space normals (OpenGL: +X red, +Y green, +Z blue)
    <id>_segment.mp4       Cryptomatte object IDs as stable flat colors (4:4:4)
    <id>_albedo.mp4        diffuse color
    <id>_lineart.mp4       ink lines from the data passes (black on white; see lines.py)
    <id>_lg_<group>.mp4    each light group alone
    <id>_pose.mp4          OpenPose-style skeleton, for clips with a rigged character
  keying clips (green/blue-screen stage, ids KY_*) also get:
    <id>_key_plate.mp4     the plate (Combined, same transform as the key layers)
    <id>_key_alpha.mp4     exact alpha (glass and other transmissive surfaces fractional)
    <id>_key_fg.mp4        despilled foreground, premultiplied on black
    <id>_key_fg_spill.mp4  foreground with the screen's spill, premultiplied
    <id>_key_clean.mp4     clean plate (subject removed)
    <id>_key_shadow.mp4    the subject's shadow on the screen (1 - plate/clean outside the subject)
  clips with a visible lens flare layer (cgdata.flares) also get:
    <id>_flare_clean.mp4   Combined + Sun (no flare)
    <id>_flare_plate.mp4   the same with the flare added
    <id>_flare_only.mp4    the flare alone, on black
Pair manifests, into LIBRARY/export/pairs/<set>.jsonl, one row per clip:
    {"id", "caption", "media_path" (target), "conditioning_path"}
for sets depth, normal, segment, albedo, lineart, pose (character clips), beauty (raw render -> finished comp)
relight_<group> (one light group -> full lighting), and, for clips rendered
with --style-pairs, toon_to_photoreal / photoreal_to_toon; keying clips add
key_alpha, key_fg, key_clean, key_shadow (each conditioned on key_plate) and
key_despill (key_fg_spill -> key_fg); flare clips add flare_removal
(flare_plate -> flare_clean) and flare_addition (the reverse). Paths are relative to
LIBRARY/export. Map the columns to your LTX trainer's dataset config.

Only clips that passed QA and were kept at the shot_curated gate are
exported, unless --include-uncurated is given.
"""

import argparse
import json
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from cgdata import captions, lines, provenance, qa

CONDITIONS = ["depth", "normal", "segment", "albedo", "lineart"]
FLARE_VIDEOS = ["flare_clean", "flare_plate", "flare_only"]
KEY_VIDEOS = ["key_plate", "key_alpha", "key_fg", "key_fg_spill", "key_clean", "key_shadow"]
# keying pair sets: name -> (media video, conditioning video)
KEY_SETS = {"key_alpha": ("key_alpha", "key_plate"), "key_fg": ("key_fg", "key_plate"),
            "key_clean": ("key_clean", "key_plate"), "key_shadow": ("key_shadow", "key_plate"),
            "key_despill": ("key_fg", "key_fg_spill")}


def box_blur(a, r):
    """Separable (2r+1)^2 box blur of a 2D array, edges clamped."""
    k = 2 * r + 1
    for axis in (0, 1):
        pad = [(r + 1, r) if i == axis else (0, 0) for i in range(2)]
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
        a = (np.take(c, range(k, c.shape[axis]), axis=axis)
             - np.take(c, range(0, c.shape[axis] - k), axis=axis)) / k
    return a.astype(np.float32)


def key_maps(L):
    """Keying videos from the plate and the Key_* layers (see kits/stage.py).
    The alpha comes from Key_FG_nospill: in Key_FG, glass refracts the
    (camera-invisible) screen and so reads opaque."""
    fg = L["Key_FG_nospill"]
    alpha = np.clip(fg[..., 3], 0, 1)
    plate, clean = L["Combined"][..., :3], L["Key_Clean"][..., :3]
    # The ratio of two noisy renders doubles the noise, so both are smoothed
    # first (the matte is soft anyway) and faint values are gated to zero.
    r = max(2, plate.shape[1] // 320)
    lp, lc = (box_blur(qa.luminance(x), r) for x in (plate, clean))
    shadow = np.clip(1 - lp / np.maximum(lc, 1e-4), 0, 1)
    shadow = np.where(shadow < 0.04, 0.0, shadow) * (alpha <= 1e-3)  # glass isn't shadow

    def gray(a):
        return np.repeat((a * 255 + 0.5).astype(np.uint8)[..., None], 3, -1)

    return {"key_plate": to_srgb8(plate), "key_alpha": gray(alpha), "key_fg": to_srgb8(fg[..., :3]),
            "key_fg_spill": to_srgb8(L["Key_FG"][..., :3]), "key_clean": to_srgb8(clean),
            "key_shadow": gray(shadow)}


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise RuntimeError("ffmpeg not found: install it or `pip install imageio-ffmpeg`") from e


def encode(frames_dir, pattern, start, fps, out, pix_fmt="yuv420p"):
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", str(fps), "-start_number", str(start),
           "-i", str(Path(frames_dir) / pattern), "-c:v", "libx264", "-crf", "14", "-preset", "slow",
           "-pix_fmt", pix_fmt]
    if pix_fmt == "yuv444p":
        cmd += ["-profile:v", "high444"]
    subprocess.run(cmd + [str(out)], check=True)


def to_srgb8(linear):
    """Scene-linear RGB -> 8-bit sRGB with a soft highlight rolloff."""
    x = np.clip(linear, 0, None)
    x = x / (1 + x * 0.25)  # gentle shoulder so light groups don't clip hard
    srgb = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    return (np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)


def segment_colors(crypto):
    """Rank-0 Cryptomatte ID (float bits) -> stable flat color per object."""
    ids = crypto[..., 0].astype(np.float32).view(np.uint32)
    h = (ids * np.uint32(2654435761)) & np.uint32(0xFFFFFF)
    rgb = np.stack([(h >> 16) & 255, (h >> 8) & 255, h & 255], -1).astype(np.uint8)
    rgb[ids == 0] = 0
    return rgb


def camera_normals(world_normal, matrix_world):
    """World-space normals -> camera space (OpenGL), encoded to 8-bit."""
    rot = np.array(matrix_world, dtype=np.float32)[:3, :3]
    rot /= np.linalg.norm(rot, axis=0, keepdims=True)
    cam = world_normal[..., :3] @ rot  # world -> camera = R^T n, row-vector form
    return ((np.clip(cam, -1, 1) * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)


def pose_image(joints, matrix_world, focal_mm, sensor_mm, width, height):
    """OpenPose-style stick figure: each bone projected through the camera and
    drawn as a colored limb with joint dots, on black."""
    from PIL import ImageDraw
    cam = np.array(matrix_world, dtype=np.float64)
    world_to_cam = np.linalg.inv(cam)
    scale = focal_mm / sensor_mm * width  # horizontal sensor fit

    def project(p):
        x, y, z, _ = world_to_cam @ np.array([*p, 1.0])
        if z >= -1e-3:  # behind the camera
            return None
        return (width / 2 + x / -z * scale, height / 2 - y / -z * scale)

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    line = max(2, width // 240)
    from cgdata.blender_constants import POSE_LIMBS
    for bone, color in POSE_LIMBS:
        if bone not in joints:
            continue
        a, b = (project(p) for p in joints[bone])
        if a and b:
            draw.line([a, b], fill=tuple(color), width=line)
            for p in (a, b):
                draw.ellipse([p[0] - line, p[1] - line, p[0] + line, p[1] + line], fill=tuple(color))
    return np.asarray(img)


def export_shot(shot_dir, out_root):
    shot_dir, out_root = Path(shot_dir), Path(out_root)
    meta = json.loads((shot_dir / "meta.json").read_text())
    sid, fps = meta["id"], meta["fps"]
    f0, f1 = meta["frame_range"]
    cam_frames = {c["frame"]: c["matrix_world"] for c in meta["camera"]["frames"]}
    groups = meta["light_groups"]
    skeleton = meta.get("skeleton")
    cam = meta["camera"]
    focals = {c["frame"]: c["focal_mm"] for c in cam["frames"]}
    out = out_root / sid
    out.mkdir(parents=True, exist_ok=True)
    final = shot_dir / "final"
    has_comp = final.is_dir() and any(final.glob("*.png"))
    ink_target = meta["style"] == "toon" and not has_comp  # outlines are a comp-stage look
    keying = "Key_FG_nospill" in meta["exr"]["light"]["layers"]
    flare = (meta.get("flare") or {}).get("visible", False)
    lit = set()  # light groups that light anything (no practicals on a stage, say)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in CONDITIONS + [f"lg_{g}" for g in groups] + (["pose"] if skeleton else []) + ["target"] + (KEY_VIDEOS if keying else []) + (FLARE_VIDEOS if flare else []):
            (tmp / name).mkdir()

        # Depth range over the whole clip, so brightness is stable in time.
        depths = []
        for f in range(f0, f1 + 1, max(1, (f1 - f0) // 8)):
            d = qa.read_layers(shot_dir / "renders" / f"{sid}_data.{f:04d}.exr")["Depth"][..., 0]
            depths.append(d[np.isfinite(d) & (d < 1e9)])
        near, far = np.percentile(np.concatenate(depths), [1, 99])
        inv_near, inv_far = 1.0 / max(near, 1e-3), 1.0 / max(far, 1e-3)

        for f in range(f0, f1 + 1):
            L = qa.read_layers(shot_dir / "renders" / f"{sid}_light.{f:04d}.exr")
            D = qa.read_layers(shot_dir / "renders" / f"{sid}_data.{f:04d}.exr")
            d = np.clip(D["Depth"][..., 0], near, far)
            inv = (1.0 / d - inv_far) / max(inv_near - inv_far, 1e-9)
            ink = lines.line_art(D)
            maps = {
                "depth": np.repeat((np.clip(inv, 0, 1) * 255 + 0.5).astype(np.uint8)[..., None], 3, -1),
                "lineart": np.repeat(((1 - ink) * 255).astype(np.uint8)[..., None], 3, -1),
                "normal": camera_normals(D["Normal"], cam_frames[f]),
                "segment": segment_colors(D["CryptoObject00"]),
                "albedo": to_srgb8(L["DiffCol"][..., :3]),
            }
            for g in groups:
                maps[f"lg_{g}"] = to_srgb8(L[f"Combined_{g}"][..., :3])
                if maps[f"lg_{g}"].any():
                    lit.add(g)
            if keying:
                maps.update(key_maps(L))
            if flare:
                X = qa.read_layers(shot_dir / "renders" / f"{sid}_flare.{f:04d}.exr")
                clean = L["Combined"][..., :3] + X["Sun"]
                maps.update({"flare_clean": to_srgb8(clean), "flare_plate": to_srgb8(clean + X["Flare"]),
                             "flare_only": to_srgb8(X["Flare"])})
            if skeleton:
                h, w = maps["depth"].shape[:2]
                maps["pose"] = pose_image(skeleton["frames"][str(f)], cam_frames[f], focals[f],
                                          cam["sensor_mm"], w, h)
            if ink_target:
                preview = np.asarray(Image.open(shot_dir / "preview" / f"{sid}.{f:04d}.png").convert("RGB"))
                maps["target"] = lines.ink(preview, ink)
            for name, img in maps.items():
                Image.fromarray(img).save(tmp / name / f"{f:04d}.png", compress_level=1)

        for name in maps:
            encode(tmp / name, "%04d.png", f0, fps, out / f"{sid}_{name}.mp4",
                   "yuv444p" if name in ("segment", "lineart", "key_alpha", "key_shadow") else "yuv420p")

    encode(shot_dir / "preview", f"{sid}.%04d.png", f0, fps, out / f"{sid}_beauty.mp4")
    if has_comp:
        encode(final, f"{sid}_final.%04d.png", f0, fps, out / f"{sid}_target.mp4")
        target_kind = "comp"
    elif ink_target:
        target_kind = "beauty_inked"  # written above, from the inked preview frames
    else:
        shutil.copy(out / f"{sid}_beauty.mp4", out / f"{sid}_target.mp4")
        target_kind = "beauty"
    return {"id": sid, "target": target_kind, "groups": [g for g in groups if g in lit], "pose": bool(skeleton), "keying": keying,
            "flare": flare and {"sun": meta["flare"].get("sun_in_view_frames", 0) > 0},
            "caption": captions.for_shot(shot_dir)["long"], "pair": meta["spec"].get("pair")}


def write_pairs(results, out_root):
    pairs = Path(out_root) / "pairs"
    pairs.mkdir(parents=True, exist_ok=True)
    sets = {c: c for c in CONDITIONS}
    sets["beauty"] = "beauty"
    rows = {}
    for r in results:
        sid = r["id"]
        target = f"{sid}/{sid}_target.mp4"
        for set_name, cond in sets.items():
            if set_name == "beauty" and r["target"] != "comp":
                continue  # beauty -> comp only means something once the comp exists
            rows.setdefault(set_name, []).append(
                {"id": sid, "caption": r["caption"], "media_path": target,
                 "conditioning_path": f"{sid}/{sid}_{cond}.mp4"})
        if r.get("pose"):
            rows.setdefault("pose", []).append(
                {"id": sid, "caption": r["caption"], "media_path": target,
                 "conditioning_path": f"{sid}/{sid}_pose.mp4"})
        if r.get("keying"):
            for set_name, (media, cond) in KEY_SETS.items():
                rows.setdefault(set_name, []).append(
                    {"id": sid, "caption": r["caption"], "media_path": f"{sid}/{sid}_{media}.mp4",
                     "conditioning_path": f"{sid}/{sid}_{cond}.mp4"})
        if r.get("flare"):
            what = "the sun" if r["flare"]["sun"] else "bright lights"
            flared = f"{r['caption']} Lens flare from {what}: a diffraction starburst, glare and ghosts."
            rows.setdefault("flare_removal", []).append(
                {"id": sid, "caption": r["caption"], "media_path": f"{sid}/{sid}_flare_clean.mp4",
                 "conditioning_path": f"{sid}/{sid}_flare_plate.mp4"})
            rows.setdefault("flare_addition", []).append(
                {"id": sid, "caption": flared, "media_path": f"{sid}/{sid}_flare_plate.mp4",
                 "conditioning_path": f"{sid}/{sid}_flare_clean.mp4"})
        for g in r["groups"]:
            rows.setdefault(f"relight_{g}", []).append(
                {"id": sid, "caption": r["caption"], "media_path": f"{sid}/{sid}_beauty.mp4",
                 "conditioning_path": f"{sid}/{sid}_lg_{g}.mp4"})
    # Style-transfer pairs: the same shot in the other style as conditioning.
    by_group = {}
    for r in results:
        if r.get("pair"):
            by_group.setdefault(r["pair"]["group"], {})[r["pair"]["style"]] = r
    for group in by_group.values():
        if len(group) < 2:
            continue
        for src, dst in (("toon", "photoreal"), ("photoreal", "toon")):
            a, b = group[src], group[dst]
            rows.setdefault(f"{src}_to_{dst}", []).append(
                {"id": b["id"], "caption": b["caption"], "media_path": f"{b['id']}/{b['id']}_target.mp4",
                 "conditioning_path": f"{a['id']}/{a['id']}_target.mp4"})
    for set_name, items in rows.items():
        with open(pairs / f"{set_name}.jsonl", "w") as fh:
            for row in items:
                fh.write(json.dumps(row) + "\n")
    return {k: len(v) for k, v in rows.items()}


def eligible(shot_dir, include_uncurated):
    meta = json.loads((shot_dir / "meta.json").read_text())
    if not meta["qa"]["passed"]:
        return False
    if include_uncurated:
        return True
    gate = provenance.gate_status(provenance._load(provenance.shot_history_path(shot_dir)))
    return gate.get("shot_curated", {}).get("decision") == "approve"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", type=Path)
    ap.add_argument("--shots", nargs="*", help="clip ids (default: all eligible)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--include-uncurated", action="store_true",
                    help="also export clips without a 'keep' shot_curated decision")
    args = ap.parse_args()

    shots = sorted(p.parent for p in (args.library / "cg").glob("*/meta.json"))
    if args.shots:
        shots = [s for s in shots if s.name in args.shots]
    shots = [s for s in shots if eligible(s, args.include_uncurated)]
    out_root = args.library / "export"
    print(f"export: {len(shots)} clips")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(export_shot, shots, [out_root] * len(shots)))
    counts = write_pairs(results, out_root)
    print("export: pair sets " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
