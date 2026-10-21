"""Keying module: spec ids, captions, export maps (no Blender needed)."""

import numpy as np

from cgdata import captions
from cgdata.comp_params import make_comp_params
from cgdata.export import box_blur, key_maps
from cgdata.spec import make_spec, make_style_pair


def test_keying_ids_and_pairs():
    spec = make_spec(7, "draft", environment="greenscreen")
    assert spec["shot_id"] == "KY_000007"
    assert make_spec(7, "draft")["shot_id"] == "CG_000007"
    pr, tn = make_style_pair(7, "draft", "greenscreen")
    assert (pr["shot_id"], tn["shot_id"]) == ("KY_000007_pr", "KY_000007_tn")
    assert pr["pair"]["group"] == "KY_000007"


def test_greenscreen_never_drawn_at_random():
    assert all(make_spec(s, "draft")["environment"]["type"] != "greenscreen" for s in range(300))


def test_comp_keeps_screen_and_skips_haze():
    params = make_comp_params(make_spec(7, "draft", environment="greenscreen"))
    assert params["light_group_gain"]["screen"] == 1.0
    assert not params["haze"]["enabled"]
    assert "screen" not in make_comp_params(make_spec(7, "draft"))["light_group_gain"]


def test_studio_caption():
    spec = make_spec(8, "draft", environment="greenscreen")
    scene = {"studio": {"screen": "blue"}, "camera": {"focal_mm": 35.0, "fstop": 4.0}, "hero": {}}
    caps = captions.generate(spec, scene)
    assert "blue screen" in caps["long"] and "keying" in caps["tags"]
    assert " in on " not in caps["long"] and "haze" not in caps["long"]


def test_box_blur_mean():
    a = np.random.default_rng(1).random((20, 30)).astype(np.float32)
    assert np.allclose(box_blur(a, 2)[10, 10], a[8:13, 8:13].mean(), atol=1e-5)
    assert box_blur(a, 3).shape == a.shape


def test_key_maps():
    h, w = 64, 96
    screen = np.zeros((h, w, 4), np.float32)
    screen[..., 1], screen[..., 3] = 0.4, 1.0
    plate, clean = screen.copy(), screen.copy()
    fg = np.zeros((h, w, 4), np.float32)
    fg[20:40, 30:50] = (0.5, 0.5, 0.5, 1.0)           # opaque subject
    plate[20:40, 30:50, :3] = 0.5
    plate[40:60, 20:80, 1] = 0.2                       # its shadow halves the screen
    L = {"Combined": plate, "Key_Clean": clean, "Key_FG_nospill": fg, "Key_FG": fg}
    m = key_maps(L)
    assert m["key_alpha"][30, 40, 0] == 255 and m["key_alpha"][5, 5, 0] == 0
    assert 100 < m["key_shadow"][50, 50, 0] < 155    # ~0.5
    assert m["key_shadow"][5, 5, 0] == 0 and m["key_shadow"][30, 40, 0] == 0
