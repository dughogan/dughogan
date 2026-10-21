"""Lens flare layer: lens model, PSF, sun projection, frame rendering."""

import math

import numpy as np

from cgdata import flares


def test_lens_is_seeded():
    assert flares.make_lens(5) == flares.make_lens(5)
    assert flares.make_lens(5) != flares.make_lens(6)


def test_psf_normalized_and_resolution_consistent():
    lens = flares.make_lens(3)
    small, big = flares.starburst_psf(lens, 480), flares.starburst_psf(lens, 1920)
    assert np.allclose(small.sum((0, 1)), 1, atol=1e-4) and np.allclose(big.sum((0, 1)), 1, atol=1e-4)
    assert big.shape[0] == flares.REF_PSF and small.shape[0] == flares.REF_PSF // 4
    assert (small >= 0).all()
    c = small.shape[0] // 2
    assert small[c, c].sum() < small.max() * 3  # the core is cut out


def test_sun_projection_center_and_behind():
    w, h = 400, 200
    cam = {"matrix_world": np.eye(4).tolist(), "focal_mm": 36.0}  # looks down -Z
    assert np.allclose(flares.project(cam, (0, 0, -1), 36.0, w, h), (200, 100))
    x, y = flares.project(cam, (math.sin(0.1), 0, -math.cos(0.1)), 36.0, w, h)
    assert x > 200 and abs(y - 100) < 1e-6
    assert flares.project(cam, (0, 0, 1), 36.0, w, h) is None


def test_dark_frame_has_no_flare():
    lens = flares.make_lens(1)
    psf = flares.starburst_psf(lens, 160)
    assert flares.flare_frame(np.full((90, 160, 3), 0.5, np.float32), lens, psf).max() == 0


def test_highlight_flares_and_sun_disc_energy():
    lens = flares.make_lens(1)
    psf = flares.starburst_psf(lens, 160)
    img = np.zeros((90, 160, 3), np.float32)
    img[40:43, 100:103] = 500.0
    out = flares.flare_frame(img, lens, psf)
    assert out.sum() > 0 and np.isfinite(out).all()
    sun = (50.3, 30.7, np.array([1000.0, 900.0, 800.0], np.float32))
    disc = flares.sun_disc(90, 160, sun, 3.0)
    assert np.allclose(disc.sum((0, 1)), sun[2], rtol=0.05)
