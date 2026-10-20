"""Ink lines from a frame's data passes: object outlines, creases, silhouettes.

    lines = line_art(data_layers)   # HxW float, 1 = ink

Three edge sources, combined:
  - object boundaries: rank-0 Cryptomatte ID changes between neighbors
  - creases: neighboring normals differ by more than CREASE_DEG
  - silhouettes: kinks in inverse depth. A plane's inverse depth is linear in
    screen space, so its second difference is ~0 even at grazing angles (a
    plain depth-jump test fills distant ground with ink); occlusion edges
    are large relative kinks
Edges are found on the full-resolution data passes, so lines sit exactly on
the geometry; a 3x3 dilation gives them a consistent ~2px weight at 1080p.
Used by export.py for the line-art conditioning video and to ink toon
targets (outlines are a comp-stage look, as in a real toon pipeline).
"""

import numpy as np

CREASE_DEG = 35.0
DEPTH_KINK = 0.04


def _neighbor_diff(a, fn):
    """Edge mask where fn(a, shifted a) is true, against right and down neighbors."""
    edge = np.zeros(a.shape[:2], dtype=bool)
    edge[:, :-1] |= fn(a[:, :-1], a[:, 1:])
    edge[:-1, :] |= fn(a[:-1, :], a[1:, :])
    return edge


def line_art(layers, width=None):
    ids = layers["CryptoObject00"][..., 0].astype(np.float32).view(np.uint32)
    edges = _neighbor_diff(ids, lambda a, b: a != b)

    n = layers["Normal"][..., :3]
    length = np.linalg.norm(n, axis=-1, keepdims=True)
    # sky (and anything without a surface) has zero normals: no creases there
    n = np.where(length > 0.5, n / np.maximum(length, 1e-6), 0.0)
    cos_limit = np.cos(np.radians(CREASE_DEG))
    edges |= _neighbor_diff(n, lambda a, b: ((a * b).sum(-1) < cos_limit)
                            & (np.abs(a).sum(-1) > 0) & (np.abs(b).sum(-1) > 0))

    d = layers["Depth"][..., 0]
    inv = 1.0 / np.where(np.isfinite(d) & (d < 1e9), np.maximum(d, 1e-3), 1e4)
    kink = np.zeros(d.shape, dtype=bool)
    for axis in (0, 1):
        second = np.abs(np.diff(inv, n=2, axis=axis))
        rel = second / np.maximum(np.take(inv, range(1, inv.shape[axis] - 1), axis=axis), 1e-6)
        pad = [(1, 1) if a == axis else (0, 0) for a in (0, 1)]
        kink |= np.pad(rel > DEPTH_KINK, pad)
    edges |= kink

    h, w = edges.shape
    radius = max(1, round((width or w) / 1000))
    padded = np.pad(edges, radius)
    out = np.zeros_like(edges)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            out |= padded[dy:dy + h, dx:dx + w]
    return out.astype(np.float32)


def ink(rgb8, lines, color=(20, 18, 24)):
    """Composite lines over an 8-bit RGB image."""
    a = lines[..., None]
    return (rgb8 * (1 - a) + np.array(color, dtype=np.float32) * a).astype(np.uint8)
