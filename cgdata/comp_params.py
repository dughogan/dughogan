"""Seeded finishing-comp parameters, shared by the Nuke builder and meta.json.

Kept free of Nuke imports so parameters can be generated, tested and recorded
anywhere. Photoreal shots get a lens/film finish; toon shots get a cleaner
graphic finish (no grain, no chromatic aberration, lighter glow).
"""

import random

LIGHT_GROUPS = ["key", "fill", "rim", "practical", "env"]


def make_comp_params(spec):
    rng = random.Random(spec["seed"] * 101 + 13)
    toon = spec["style"] == "toon"
    keying = spec["environment"]["type"] == "greenscreen"
    fog = spec["atmosphere"]["fog"] and not keying  # no atmosphere on the stage

    def gain(lo, hi):
        return round(rng.uniform(lo, hi), 3)

    params = {
        "style": spec["style"],
        # Per-light-group relight: the comp is rebuilt from light groups so
        # each can be balanced, exactly as a lighting/comp TD would.
        "light_group_gain": {
            "key": gain(0.85, 1.25),
            "fill": gain(0.6, 1.3),
            "rim": gain(0.8, 1.6),
            "practical": gain(0.8, 1.8),
            "env": gain(0.7, 1.2),
        },
        "haze": {
            "enabled": (not toon) and (fog or rng.random() < 0.5) and not keying,
            "density": round(rng.uniform(0.005, 0.03), 4),
            "color": [round(c, 3) for c in (rng.uniform(0.5, 0.7), rng.uniform(0.55, 0.75), rng.uniform(0.65, 0.9))],
        },
        "defocus": {
            "enabled": not toon or rng.random() < 0.3,
            "size": round(rng.uniform(4, 14) if not toon else rng.uniform(2, 5), 2),
            "max_size": 40,
        },
        "motion_blur": {"enabled": True, "shutter": round(rng.uniform(0.35, 0.6), 3)},
        "glow": {
            "enabled": True,
            "tolerance": round(rng.uniform(0.8, 1.5), 3),
            "brightness": round(rng.uniform(0.15, 0.5) if not toon else rng.uniform(0.05, 0.2), 3),
            "size": round(rng.uniform(15, 60), 1),
        },
        "chromatic_aberration": {
            "enabled": not toon,
            "amount": round(rng.uniform(0.0008, 0.003), 5),
        },
        "vignette": {"amount": round(rng.uniform(0.1, 0.35) if not toon else rng.uniform(0.0, 0.1), 3)},
        "grade": {
            "saturation": round(rng.uniform(0.85, 1.15) if not toon else rng.uniform(1.0, 1.25), 3),
            "contrast": round(rng.uniform(0.95, 1.15), 3),
            "gamma": round(rng.uniform(0.9, 1.1), 3),
            "gain": round(rng.uniform(0.9, 1.15), 3),
            "lift": round(rng.uniform(-0.01, 0.015), 4),
        },
        "grain": {
            "enabled": not toon,
            "intensity": round(rng.uniform(0.3, 1.0), 3),
            "size": round(rng.uniform(1.0, 2.5), 2),
        },
    }
    if keying:
        # The screen stays as shot: a keyer is trained on the plate as it is.
        params["light_group_gain"]["screen"] = 1.0
    return params
