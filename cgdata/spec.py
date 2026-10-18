"""Shot spec generation.

A shot spec is a plain JSON recipe that fully determines one dataset clip:
style, environment, props, lighting, camera move, render settings. The same
spec + seed always rebuilds the same scene, so the spec is stored with every
clip and doubles as its provenance record.

Usage:
    python -m cgdata.spec --count 10 --seed 1000 --out specs/
"""

import argparse
import json
import random
from pathlib import Path

SPEC_VERSION = 1

STYLES = ["photoreal", "toon"]
ENVIRONMENTS = ["city_block", "canyon"]
CAMERA_MOVES = ["dolly_in", "orbit", "truck", "crane"]
TIMES_OF_DAY = ["morning", "noon", "golden_hour", "dusk"]
HERO_TYPES = ["glass_sculpture", "chrome_sculpture", "sss_blob", "neon_totem", "stone_monolith"]

# Render presets. "pilot" is for buyer samples; "draft" is for pipeline testing.
# Frame counts are 8n+1 (97 = 8*12+1), which LTX-Video training expects.
QUALITY = {
    "draft": {"resolution": [480, 270], "samples": 16, "frames": 3},
    "preview": {"resolution": [960, 540], "samples": 64, "frames": 25},
    "pilot": {"resolution": [1920, 1080], "samples": 512, "frames": 97},
    "pilot_4k": {"resolution": [3840, 2160], "samples": 512, "frames": 97},
}


def make_spec(seed, quality="pilot", style=None, environment=None):
    """Build a deterministic shot spec from a seed."""
    rng = random.Random(seed)
    q = QUALITY[quality]
    style = style or rng.choice(STYLES)
    environment = environment or rng.choice(ENVIRONMENTS)

    spec = {
        "spec_version": SPEC_VERSION,
        "shot_id": f"CG_{seed:06d}",
        "seed": seed,
        "style": style,
        "environment": {
            "type": environment,
            "seed": rng.randrange(1 << 30),
            "density": round(rng.uniform(0.4, 1.0), 3),
            "extent": round(rng.uniform(30.0, 60.0), 2),
        },
        "hero": {
            "type": rng.choice(HERO_TYPES),
            "scale": round(rng.uniform(0.7, 1.4), 3),
            "hue": round(rng.random(), 3),
        },
        "props": {
            "count": rng.randint(6, 24),
            "seed": rng.randrange(1 << 30),
        },
        "atmosphere": {
            "fog": rng.random() < 0.35,
            "fog_density": round(rng.uniform(0.005, 0.03), 4),
        },
        "lighting": {
            "time_of_day": rng.choice(TIMES_OF_DAY),
            "sun_rotation_deg": round(rng.uniform(0, 360), 1),
            "key_intensity": round(rng.uniform(0.6, 1.4), 3),
            "fill_ratio": round(rng.uniform(0.1, 0.5), 3),
            "rim_intensity": round(rng.uniform(0.0, 1.5), 3),
            "practicals": rng.randint(0, 6),
        },
        "camera": {
            "move": rng.choice(CAMERA_MOVES),
            "sensor_mm": 36.0,
            # Hero size as a fraction of frame height.
            "framing": round(rng.uniform(0.25, 0.7), 3),
            # Where in the clear zone the camera sits (0 = close, 1 = far);
            # the focal length follows from distance and framing.
            "distance_frac": round(rng.uniform(0.0, 1.0), 3),
            "height_offset": round(rng.uniform(-0.5, 3.0), 2),
            "azimuth_deg": round(rng.uniform(0, 360), 1),
            "travel": round(rng.uniform(0.15, 0.4), 3),
            "fstop": rng.choice([1.4, 2.0, 2.8, 4.0, 5.6, 8.0]),
        },
        "render": {
            "quality": quality,
            "resolution": q["resolution"],
            "fps": 24,
            "frame_start": 1001,
            "frame_end": 1001 + q["frames"] - 1,
            "samples": q["samples"],
            # Denoising is off so the light AOVs sum exactly to Combined; the
            # denoising data passes are stored so buyers can denoise later.
            "denoise_combined": False,
        },
    }
    return spec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--quality", choices=sorted(QUALITY), default="pilot")
    ap.add_argument("--style", choices=STYLES)
    ap.add_argument("--environment", choices=ENVIRONMENTS)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        spec = make_spec(args.seed + i, args.quality, args.style, args.environment)
        path = args.out / f"{spec['shot_id']}.json"
        path.write_text(json.dumps(spec, indent=2))
        print(path)


if __name__ == "__main__":
    main()
