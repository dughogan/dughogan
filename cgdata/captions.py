"""Captions for dataset clips, written from what is actually in the scene.

Every fact comes from the clip's spec and scene record (environment, hero,
light, lens, camera move, comp finish), so captions are accurate by
construction. Wording varies per clip (seeded) so a model doesn't learn one
template. Three forms: `short` (one line), `long` (2-3 sentences, for video
training) and `tags`.

A human edit overrides the generated text: `review.py captions` stores it in
<shot>/captions_edited.json and logs it in the clip's provenance history as
a person's note.
"""

import colorsys
import json
import random
from pathlib import Path

STYLE = {
    "photoreal": ["photorealistic CG", "photoreal 3D render", "realistic CGI"],
    "toon": ["stylized cel-shaded 3D animation", "toon-shaded CG animation", "cartoon-style 3D render"],
}
ENVIRONMENT = {
    "city_block": ["a paved city plaza ringed by brick and stone buildings with storefronts",
                   "a city square surrounded by apartment blocks, street lamps and benches",
                   "an urban plaza between mid-rise buildings with lit windows"],
    "canyon": ["a desert canyon with layered sandstone rock formations",
               "a dry canyon floor among stacked red-rock outcrops",
               "a sandy canyon with weathered strata rocks and sparse shrubs"],
    "interior": ["a sunlit loft interior with wooden floors, shelves and a sofa",
                 "a furnished open-plan room with tall windows and floor lamps",
                 "a lived-in apartment interior with bookshelves, rugs and plants"],
    "meadow": ["a grassy meadow of rolling hills with scattered trees",
               "an open meadow with tufted grass, shrubs and leafy trees",
               "rolling green hills dotted with trees and boulders"],
}
HERO = {
    "glass_sculpture": "a clear glass torus sculpture",
    "chrome_sculpture": "a polished chrome sculpture with a rippled surface",
    "sss_blob": "a translucent, waxy organic sculpture",
    "neon_totem": "a painted column ringed with glowing neon bands",
    "stone_monolith": "a carved stone monolith",
    "vehicle": "a glossy compact car",
    "robot_arm": "a heavy industrial robot arm on a plinth",
    "torus_knot": "a polished metal torus-knot sculpture",
    "crystal_cluster": "a cluster of clear crystals on a rock",
    "twisted_column": "a twisting stacked-stone column",
}
LIGHT = {
    "morning": "soft morning light",
    "noon": "bright midday sun with crisp shadows",
    "golden_hour": "warm golden-hour light with long shadows",
    "dusk": "dusk light",
}
MOVE = {
    "dolly_in": ["the camera slowly dollies in", "a slow push-in toward it"],
    "orbit": ["the camera orbits around it", "a smooth orbiting camera move"],
    "truck": ["the camera trucks sideways past it", "a lateral tracking move"],
    "crane": ["the camera cranes upward", "a rising crane shot"],
}
HUES = [(0.04, "red"), (0.1, "orange"), (0.18, "yellow"), (0.45, "green"), (0.55, "cyan"),
        (0.72, "blue"), (0.85, "purple"), (0.96, "pink"), (1.01, "red")]


def hue_name(h):
    return next(name for limit, name in HUES if h % 1.0 < limit)


def color_name(rgb):
    """Plain-language name for a linear RGB color (neutrals included)."""
    h, s, v = colorsys.rgb_to_hsv(*rgb[:3])
    if s < 0.18:
        return "black" if v < 0.08 else "white" if v > 0.7 else "silver" if v > 0.35 else "grey"
    return hue_name(h)


def lens_phrase(focal):
    if focal < 28:
        return "wide-angle lens"
    if focal < 45:
        return "normal lens"
    if focal < 85:
        return "portrait-length lens"
    return "telephoto lens"


def _cap(text):
    return text[:1].upper() + text[1:]


def generate(spec, scene, comp=None):
    """Captions from a shot's spec and scene.json (and comp params, if any)."""
    rng = random.Random(spec["seed"] * 7919 + 1)
    pick = rng.choice
    env, style = spec["environment"]["type"], spec["style"]
    hero = HERO[spec["hero"]["type"]]
    if spec["hero"]["type"] in ("sss_blob", "neon_totem", "vehicle", "robot_arm"):
        rgb = (scene.get("hero") or {}).get("color")
        name = color_name(rgb) if rgb else hue_name(spec["hero"]["hue"])
        hero = hero.replace("a ", f"{'an' if name[0] in 'aeiou' else 'a'} {name} ", 1)
    tod = spec["lighting"]["time_of_day"]
    light = LIGHT[tod]
    if tod == "dusk":
        light += {"city_block": ", lit by street lamps and windows",
                  "interior": ", the room lit by its lamps"}.get(env, " fading to blue")
    focal = scene["camera"]["focal_mm"]
    shallow = scene["camera"]["fstop"] <= 2.8
    move = pick(MOVE[spec["camera"]["move"]])
    fog = spec["atmosphere"]["fog"]
    look = pick(STYLE[style])

    short = f"{_cap(look)}: {hero} in {pick(ENVIRONMENT[env])}, {LIGHT[tod]}."
    sentences = [
        f"A {look} shot of {hero} standing in {pick(ENVIRONMENT[env])}.",
        f"{_cap(light)}{', with light haze in the air' if fog else ''}; {move}, "
        f"filmed on a {lens_phrase(focal)}{' with shallow depth of field' if shallow else ''}.",
    ]
    if comp and style == "photoreal" and comp.get("grain", {}).get("enabled"):
        sentences.append("Finished with subtle film grain, lens glow and a cinematic grade.")
    elif comp and style == "toon":
        sentences.append("Clean graphic finish with flat, saturated color.")
    tags = [style, env, spec["hero"]["type"], tod, spec["camera"]["move"],
            lens_phrase(focal).replace(" lens", ""), *(["shallow dof"] if shallow else []),
            *(["haze"] if fog else []), "cg", "vfx"]
    return {"short": short, "long": " ".join(sentences), "tags": tags, "source": "generated"}


def for_shot(shot_dir):
    """Generated captions, with any human edits applied on top."""
    shot_dir = Path(shot_dir)
    spec = json.loads((shot_dir / "spec.json").read_text())
    scene = json.loads((shot_dir / "scene.json").read_text())
    comp_path = shot_dir / "comp" / f"{spec['shot_id']}_comp.json"
    comp = json.loads(comp_path.read_text())["params"] if comp_path.exists() else None
    caps = generate(spec, scene, comp)
    edited = shot_dir / "captions_edited.json"
    if edited.exists():
        for key, entry in json.loads(edited.read_text()).items():
            caps[key] = entry["text"]
            caps.setdefault("edited", {})[key] = {k: v for k, v in entry.items() if k != "text"}
    return caps
