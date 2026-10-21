"""Lens flares rendered from a clip's own light, as a separate additive layer.

    python -m cgdata.flares LIBRARY/cg/CG_000123 [...]   (photoreal clips; toon is skipped)

Writes renders/<id>_flare.####.exr (half float, scene-linear) with two layers:
    Flare   the stray light the lens scatters (starburst, halo, ghosts)
    Sun     the sun's own disc, which the render lacks (black when the sun
            is off screen or blocked); clipped to the half-float range
and flare.json (the lens and per-frame stats). The render itself is not
touched, so every clip gets an exact pair: clean = Combined + Sun,
flared = clean + Flare. Flared -> clean is flare removal, the reverse flare
addition, and Flare alone is a flare element for compositing.

The lens (seeded per clip) is a parametric model, not a ray trace through a
real lens prescription:
  - Diffraction starburst: the point spread function of the clip's aperture
    (an n-blade polygon with rounded blades and dust), computed as
    |FFT(pupil)|^2 at seven wavelengths and summed to RGB, so streak count
    follows the blade count (n spikes for even n, 2n for odd) and the
    streaks show spectral fringing. Every highlight above a threshold is
    convolved with it, plus a broad veiling-glare halo.
  - Ghosts: internal reflections, drawn as aperture-shaped discs on the line
    from each source through the frame center (position t along that line,
    size, coating tint, a bright rim and slight per-channel dispersion).
  - The sun: the render has no sun disc (the sun lamp is the key light), so
    the sun is added as a source from its direction in scene.json, on frames
    where Blender's ray cast found it unblocked from the lens. It may be just
    outside the frame: its glare and ghosts still land inside.
Sources come from the rendered frame itself and the lens is fixed per clip,
so flares track their sources from frame to frame.
"""

import argparse
import json
import math
import random
from pathlib import Path

import numpy as np
import OpenEXR

from cgdata import qa

THRESHOLD = 3.0      # scene-linear luminance above which a pixel is a flare source
CELLS = 24           # source grid rows; each cell's highlight energy is one ghost source
WAVELENGTHS = np.linspace(420, 680, 7)
# Sun disc radiance in the render's scene-linear units, per unit of sun lamp
# strength. Tuned by eye so a visible sun clips hard and flares strongly.
SUN_RADIANCE = 50000.0
HALF_MAX = 60000.0
REF_WIDTH, REF_PSF = 1920, 1024   # the PSF is designed at this frame width / grid size
COATINGS = [(1.0, 0.75, 0.35), (0.85, 0.45, 1.0), (0.45, 1.0, 0.55), (0.4, 0.85, 1.0),
            (0.55, 0.6, 1.0), (1.0, 0.55, 0.55)]


def make_lens(seed):
    rng = random.Random(seed * 7907 + 5)
    blades = rng.choice([5, 6, 6, 7, 8, 9])
    ghosts = []
    for _ in range(rng.randint(4, 10)):
        t = rng.choice([rng.uniform(-1.6, -0.2), rng.uniform(0.2, 0.9), rng.uniform(1.1, 1.5)])
        ghosts.append({
            "t": round(t, 3),
            "radius": round(rng.uniform(0.01, 0.12), 4),   # fraction of frame height
            "strength": round(10 ** rng.uniform(-4.5, -3.0), 7),  # fraction of source energy
            "tint": [round(c * rng.uniform(0.8, 1.0), 3) for c in rng.choice(COATINGS)],
            "rim": round(rng.uniform(0.0, 0.8), 3),
            "softness": round(rng.uniform(0.04, 0.3), 3),
            "dispersion": round(rng.uniform(0.0, 0.04), 4),
        })
    return {
        "seed": seed,
        "blades": blades,
        "blade_rotation": round(rng.uniform(0, 2 * math.pi / blades), 4),
        "blade_curvature": round(rng.uniform(0.0, 0.35), 3),  # 0 straight blades (strong spikes), 1 round
        "pupil_fraction": round(rng.uniform(0.05, 0.1), 4),   # pupil radius / FFT grid: smaller = longer streaks
        "dust": rng.randint(0, 12),
        "scatter": round(rng.uniform(0.01, 0.05), 4),       # fraction of highlight energy in the starburst
        "halo": round(rng.uniform(0.1, 0.4), 3),             # share of that in the broad veiling halo
        "halo_radius": round(rng.uniform(0.03, 0.12), 4),    # fraction of frame width
        "ghosts": ghosts,
    }


# ------------------------------------------------------------------ starburst

def pupil(lens, n, radius, rng):
    """Aperture transmission on an n x n grid: rounded n-gon plus dust specks."""
    y, x = np.mgrid[:n, :n].astype(np.float32) - n / 2
    r = np.hypot(x, y)
    a = np.arctan2(y, x) - lens["blade_rotation"]
    sector = 2 * np.pi / lens["blades"]
    edge = np.cos(np.pi / lens["blades"]) / np.cos((a % sector) - sector / 2)  # polygon edge / circumradius
    edge = edge + (1 - edge) * lens["blade_curvature"]
    mask = np.clip((radius * edge - r) + 0.5, 0, 1)  # one-pixel antialiased edge
    for _ in range(lens["dust"]):
        cx, cy = (rng.uniform(-0.8, 0.8) * radius for _ in range(2))
        mask *= np.clip(np.hypot(x - cx, y - cy) - rng.uniform(0.3, 1.5) * radius * 0.03, 0, 1)
    return mask


def wavelength_rgb(nm):
    """Approximate linear-RGB response to a wavelength (sums of Gaussians)."""
    def g(mu, s):
        return math.exp(-0.5 * ((nm - mu) / s) ** 2)
    return np.array([g(600, 40) + 0.35 * g(445, 20), g(545, 45), g(450, 30)], np.float32)


def starburst_psf(lens, width):
    """Stray-light PSF for a frame `width` pixels wide: centered, each
    channel summing to 1. Computed at a 1920-wide reference scale and
    resampled, so a lens looks the same at every resolution. The diffraction
    core (the source's own image, out to about the second Airy ring) is
    removed: the render already holds the source, so the flare layer carries
    only the light the lens scatters away from it."""
    from PIL import Image
    size = REF_PSF
    rng = random.Random(lens["seed"])
    weights = np.stack([wavelength_rgb(w) for w in WAVELENGTHS])
    weights /= weights.sum(0, keepdims=True)  # a white source stays white
    psf = np.zeros((size, size, 3), np.float32)
    base = lens["pupil_fraction"] * size
    for wl, w in zip(WAVELENGTHS, weights):
        # The far-field pattern scales with wavelength: in grid units that is
        # the same as shrinking the pupil by 550/wl.
        p = pupil(lens, size, base * 550.0 / wl, random.Random(rng.random()))
        mono = np.abs(np.fft.fftshift(np.fft.fft2(p))) ** 2
        psf += (mono / mono.sum())[..., None] * w
    y, x = np.mgrid[:size, :size].astype(np.float32) - size / 2
    r = np.hypot(x, y)
    core = 2.2 / (2 * lens["pupil_fraction"])  # ~second Airy zero, in pixels
    cut = 1 - np.exp(-(r / core) ** 2)          # soft, so small suns get no dark ring
    window = np.clip(1 - (r / (size / 2)) ** 2, 0, 1) ** 2  # fades to zero: no hard stamp edges
    psf *= (cut * window)[..., None]
    psf /= psf.sum((0, 1), keepdims=True)
    halo = cut * window / (1 + (r / (lens["halo_radius"] * REF_WIDTH)) ** 2) ** 1.5
    halo /= halo.sum()
    psf = (1 - lens["halo"]) * psf + lens["halo"] * halo[..., None]
    out = max(64, int(round(size * width / REF_WIDTH)) // 2 * 2)
    if out != size:
        psf = np.stack([np.asarray(Image.fromarray(psf[..., c]).resize((out, out), Image.BILINEAR))
                        for c in range(3)], -1)
        psf = np.maximum(psf, 0)
        psf /= psf.sum((0, 1), keepdims=True)
    return psf.astype(np.float32)


def convolve(image, psf):
    """Same-size FFT convolution of an HxWx3 image with a centered PSF."""
    h, w = image.shape[:2]
    k = psf.shape[0]
    fh, fw = h + k, w + k
    out = np.empty_like(image)
    for c in range(3):
        f = np.fft.rfft2(image[..., c], (fh, fw)) * np.fft.rfft2(psf[..., c], (fh, fw))
        full = np.fft.irfft2(f, (fh, fw))
        out[..., c] = full[k // 2:k // 2 + h, k // 2:k // 2 + w]
    return out


def stamp(canvas, psf, cx, cy, energy):
    """Add psf * energy centered at (cx, cy), cropped to the canvas."""
    h, w = canvas.shape[:2]
    k = psf.shape[0]
    x0, y0 = int(round(cx)) - k // 2, int(round(cy)) - k // 2
    xs, ys = max(0, x0), max(0, y0)
    xe, ye = min(w, x0 + k), min(h, y0 + k)
    if xs < xe and ys < ye:
        canvas[ys:ye, xs:xe] += psf[ys - y0:ye - y0, xs - x0:xe - x0] * energy


# --------------------------------------------------------------------- ghosts

def sources(bright, rows=CELLS):
    """Highlight energy per grid cell, with its energy-weighted centroid."""
    h, w = bright.shape[:2]
    cell = max(4, h // rows)
    gh, gw = h // cell, w // cell
    lum = qa.luminance(bright)[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell)
    rgb = bright[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell, 3)
    energy = lum.sum((1, 3))
    yy, xx = np.mgrid[:gh * cell, :gw * cell].astype(np.float32)
    cy = (yy.reshape(gh, cell, gw, cell) * lum).sum((1, 3)) / np.maximum(energy, 1e-9)
    cx = (xx.reshape(gh, cell, gw, cell) * lum).sum((1, 3)) / np.maximum(energy, 1e-9)
    color = rgb.sum((1, 3))
    out = []
    for i, j in zip(*np.nonzero(energy > 0)):
        out.append((float(cx[i, j]), float(cy[i, j]), color[i, j]))
    out.sort(key=lambda s: -float(s[2].sum()))
    return out[:64]


def draw_ghosts(canvas, srcs, lens):
    h, w = canvas.shape[:2]
    center = np.array([w / 2, h / 2], np.float32)
    sector = 2 * np.pi / lens["blades"]
    for sx, sy, energy in srcs:
        axis = np.array([sx, sy], np.float32) - center
        for g in lens["ghosts"]:
            radius = g["radius"] * h
            peak = energy * g["strength"] / (math.pi * radius ** 2)
            if peak.max() * max(g["tint"]) < 1e-4:
                continue
            for c in range(3):
                t = g["t"] * (1 + g["dispersion"] * (c - 1))  # red/blue land slightly apart
                gx, gy = center + axis * t
                x0, x1 = int(max(0, gx - radius * 1.3)), int(min(w, gx + radius * 1.3 + 1))
                y0, y1 = int(max(0, gy - radius * 1.3)), int(min(h, gy + radius * 1.3 + 1))
                if x0 >= x1 or y0 >= y1:
                    continue
                y, x = np.mgrid[y0:y1, x0:x1].astype(np.float32)
                r = np.hypot(x - gx, y - gy)
                a = np.arctan2(y - gy, x - gx) - lens["blade_rotation"]
                edge = radius * np.cos(np.pi / lens["blades"]) / np.cos((a % sector) - sector / 2)
                d = (edge - r) / (radius * g["softness"] + 1e-6)
                inside = np.clip(d, 0, 1)
                rim = np.exp(-np.abs(d - 0.5) * 3) * g["rim"]
                canvas[y0:y1, x0:x1, c] += (inside * (1 - g["rim"] * 0.5) + rim) * peak[c] * g["tint"][c]


# ------------------------------------------------------------------------ sun

def project(cam_frame, direction, sensor_mm, w, h):
    """Screen position of a direction (a point at infinity), or None if behind."""
    rot = np.array(cam_frame["matrix_world"], np.float64)[:3, :3]
    rot /= np.linalg.norm(rot, axis=0, keepdims=True)
    d = rot.T @ np.asarray(direction, np.float64)  # world -> camera
    if d[2] >= -1e-6:
        return None
    scale = cam_frame["focal_mm"] / sensor_mm * w
    return (w / 2 + d[0] / -d[2] * scale, h / 2 - d[1] / -d[2] * scale)


def sun_source(meta, frame, w, h):
    cam = meta["camera"]
    sun = cam.get("sun")
    entry = next((c for c in cam["frames"] if c["frame"] == frame), None)
    if not sun or not entry or not entry.get("sun_visible"):
        return None
    pos = project(entry, sun["direction"], cam["sensor_mm"], w, h)
    if pos is None or not (-w < pos[0] < 2 * w and -h < pos[1] < 2 * h):
        return None
    px_per_rad = entry["focal_mm"] / cam["sensor_mm"] * w
    disc_px = math.pi * (math.radians(sun["angle_deg"]) / 2 * px_per_rad) ** 2
    energy = np.array(sun["color"], np.float32) * sun["strength"] * SUN_RADIANCE * max(disc_px, 1.0)
    return pos[0], pos[1], energy, math.radians(sun["angle_deg"]) / 2 * px_per_rad


# ----------------------------------------------------------------------- shot

def sun_disc(h, w, sun, radius):
    """The sun's own image (the render has none): an antialiased disc holding
    the sun's energy. Belongs to the clean plate, not to the flare."""
    disc = np.zeros((h, w, 3), np.float32)
    radius = max(radius, 0.75)
    x0, x1 = int(max(0, sun[0] - radius - 2)), int(min(w, sun[0] + radius + 3))
    y0, y1 = int(max(0, sun[1] - radius - 2)), int(min(h, sun[1] + radius + 3))
    if x0 >= x1 or y0 >= y1:
        return disc
    y, x = np.mgrid[y0:y1, x0:x1].astype(np.float32) + 0.5
    cover = np.clip(radius - np.hypot(x - sun[0], y - sun[1]) + 0.5, 0, 1)
    disc[y0:y1, x0:x1] = cover[..., None] * (sun[2] / max(math.pi * radius ** 2, 1.0))
    return np.minimum(disc, HALF_MAX)


def flare_frame(combined, lens, psf, sun=None):
    lum = qa.luminance(combined)
    bright = combined * (np.maximum(lum - THRESHOLD, 0) / np.maximum(lum, 1e-6))[..., None]
    flare = convolve(bright, psf) * lens["scatter"]
    srcs = sources(bright)
    if sun is not None:
        stamp(flare, psf, sun[0], sun[1], sun[2] * lens["scatter"])
        srcs.insert(0, sun[:3])
    draw_ghosts(flare, srcs, lens)
    return np.clip(flare, 0, HALF_MAX)


def write_exr(path, layers):
    header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
    channels = {f"{name}.{c}": np.ascontiguousarray(a[..., i].astype(np.float16))
                for name, a in layers.items() for i, c in enumerate("RGB")}
    OpenEXR.File(header, channels).write(str(path))


def render_shot(shot_dir):
    """Write the flare layer for a photoreal clip; returns flare.json (None for toon)."""
    shot_dir = Path(shot_dir)
    spec = json.loads((shot_dir / "spec.json").read_text())
    scene = json.loads((shot_dir / "scene.json").read_text())
    if spec["style"] != "photoreal":
        return None
    sid = spec["shot_id"]
    r = spec["render"]
    lens = make_lens(spec["seed"])
    w, h = r["resolution"]
    psf = starburst_psf(lens, w)
    stats = []
    for f in range(r["frame_start"], r["frame_end"] + 1):
        combined = qa.read_layers(shot_dir / "renders" / f"{sid}_light.{f:04d}.exr")["Combined"][..., :3]
        sun = sun_source({"camera": scene["camera"]}, f, w, h)
        flare = flare_frame(combined, lens, psf, sun)
        disc = sun_disc(h, w, sun[:3], sun[3]) if sun else np.zeros_like(flare)
        write_exr(shot_dir / "renders" / f"{sid}_flare.{f:04d}.exr", {"Flare": flare, "Sun": disc})
        lum = qa.luminance(flare)
        in_view = bool(sun is not None and 0 <= sun[0] < w and 0 <= sun[1] < h)
        stats.append({"frame": f, "sun": sun is not None, "sun_in_view": in_view, "max": round(float(lum.max()), 4),
                      "visible_fraction": round(float((lum > 0.02).mean()), 4)})
    info = {"layers": {"Flare": "stray light: add to Combined (+ Sun) for the flared plate",
                       "Sun": "the sun's disc (the render has none): add to Combined for the clean plate"},
            "file": f"renders/{sid}_flare.####.exr", "lens": lens,
            "model": "parametric (FFT aperture starburst + aperture ghosts)",
            "threshold": THRESHOLD, "frames": stats,
            "visible": any(s["visible_fraction"] > 0.002 for s in stats)}
    (shot_dir / "flare.json").write_text(json.dumps(info, indent=2))
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shots", nargs="+", type=Path)
    args = ap.parse_args()
    for shot in args.shots:
        info = render_shot(shot)
        print(f"flares: {shot.name}: " + ("skipped (toon)" if info is None else
              f"{'visible' if info['visible'] else 'faint'}, sun on {sum(s['sun'] for s in info['frames'])} frames"))


if __name__ == "__main__":
    main()
