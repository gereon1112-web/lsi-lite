"""Die Bahnen einer Schicht: Umriss am Bauteil, Wand, Fuellung und Fahrreihenfolge."""

import math

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from bausteine import bauteil


def outline(xs, ys, d):
    """Bereich, in dem d > 0 ist, als shapely-Flaeche (mit Loechern und Inseln)."""
    from contourpy import contour_generator
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    if d.max() <= 0:
        return Polygon()
    points, offsets = contour_generator(xs, ys, d, fill_type="OuterOffset").filled(0.0, d.max() + 1)
    polys = []
    for p, o in zip(points, offsets):
        rings = [p[a:b] for a, b in zip(o[:-1], o[1:])]
        polys.append(Polygon(rings[0], rings[1:]))
    return unary_union(polys).buffer(0)


def rings(geom):
    """Alle Randlinien einer shapely-Flaeche als geschlossene Linienzuege."""
    polys = getattr(geom, "geoms", [geom])
    out = []
    for poly in polys:
        if poly.is_empty:
            continue
        out += [np.asarray(r.coords)[:, :2] for r in [poly.exterior, *poly.interiors]]
    return [r for r in out if len(r) > 3]


def zigzag(area, gap, angle):
    """Parallele Linien im Abstand gap, Nachbarenden zu Zickzack verbunden."""
    from shapely import affinity
    from shapely.geometry import LineString
    if area.is_empty:
        return []
    turned = affinity.rotate(area, -angle, origin=(0, 0), use_radians=True)
    x0, y0, x1, y1 = turned.bounds
    lines = []
    for n, y in enumerate(np.arange(y0 + 0.5 * gap, y1, gap)):
        cut = turned.intersection(LineString([(x0 - 1, y), (x1 + 1, y)]))
        segs = sorted((np.asarray(g.coords) for g in getattr(cut, "geoms", [cut])
                       if g.geom_type == "LineString" and g.length > 0),
                      key=lambda s: s[:, 0].min())
        segs = [s[np.argsort(s[:, 0])] for s in segs]
        lines += [s[::-1] for s in segs[::-1]] if n % 2 else segs
    c, s = math.cos(angle), math.sin(angle)
    lines = [seg @ np.array([[c, s], [-s, c]]) for seg in lines]
    merged = [lines[0]] if lines else []
    for seg in lines[1:]:
        if np.linalg.norm(seg[0] - merged[-1][-1]) < 2 * gap:
            merged[-1] = np.vstack([merged[-1], seg])
        else:
            merged.append(seg)
    return [(m, False) for m in merged]


def layer_paths(region, k, cfg, w, field=None):
    """Eine Wand und Fuellung einer Schicht in der Draufsicht: Liste (Punkte, geschlossen)."""
    paths = [(r, True) for r in rings(region.buffer(-0.5 * w))]
    density = 100 if k == 0 else cfg["density"]
    if density <= 0:
        return paths
    gap = w * 100.0 / density
    inset = 1.5 * w
    if cfg["infill"] == "zigzag":
        return paths + zigzag(region.buffer(-inset + 0.1 * w), gap,
                              math.radians(45.0 + 90.0 * k))
    if cfg["infill"] == "explizit":
        return paths + streamlines(region.buffer(-inset + 0.1 * w), gap, field)
    while True:
        ring = rings(region.buffer(-inset))
        if not ring:
            return paths
        paths += [(r, True) for r in ring]
        inset += gap


class DirectionField:
    """Zugrichtung sigma_1 in der Schichtebene, in die Draufsicht gelegt, auf dem Raster."""

    def __init__(self, xs, ys, layer, fem_points, sigma, refs):
        self.xs, self.ys = xs, ys
        gy, gx = np.gradient(layer, ys, xs)
        normal = np.dstack([-gx, -gy, np.ones_like(layer)])
        normal /= np.linalg.norm(normal, axis=2, keepdims=True)
        pts = np.column_stack([np.tile(xs, len(ys)), np.repeat(ys, len(xs)), layer.ravel()])
        e1, weight = bauteil.sample_tension(pts, fem_points, sigma, refs)
        e1 = e1.reshape(normal.shape)
        d = (e1 - np.sum(e1 * normal, axis=2, keepdims=True) * normal)[:, :, :2]
        size = np.linalg.norm(d, axis=2, keepdims=True)
        self.d = np.where(size > 1e-6, d / np.maximum(size, 1e-6), 0.0)
        self.weight = RegularGridInterpolator((ys, xs), weight.reshape(layer.shape),
                                              bounds_error=False, fill_value=0.0)

    def __call__(self, p, prev=None):
        """Einheitsrichtung am Punkt p; None, wo die Nachbarwerte nicht zusammenpassen."""
        fx = (p[0] - self.xs[0]) / (self.xs[1] - self.xs[0])
        fy = (p[1] - self.ys[0]) / (self.ys[1] - self.ys[0])
        i = int(np.clip(fx, 0, len(self.xs) - 2))
        j = int(np.clip(fy, 0, len(self.ys) - 2))
        ax, ay = fx - i, fy - j
        corners = self.d[j:j + 2, i:i + 2].reshape(4, 2)
        share = np.array([(1 - ax) * (1 - ay), ax * (1 - ay), (1 - ax) * ay, ax * ay])
        # ohne Vorzeichen: erst auf die vorige Richtung ausrichten, dann mitteln
        ref = prev if prev is not None else corners[np.argmax(share)]
        v = share @ (corners * np.sign(corners @ ref)[:, None])
        size = np.linalg.norm(v)
        return v / size if size > 0.3 else None


class Occupancy:
    """Gelegte Bahnpunkte in Rasterzellen, fuer schnelle Abstandsfragen."""

    def __init__(self, cell):
        self.cell, self.cells = cell, {}

    def add(self, points):
        for q in points:
            self.cells.setdefault((int(q[0] // self.cell), int(q[1] // self.cell)), []).append(q)

    def near(self, p, r):
        """Liegt ein gelegter Punkt naeher als r (<= Zellgroesse) an p?"""
        i, j = int(p[0] // self.cell), int(p[1] // self.cell)
        return any((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 < r * r
                   for di in (-1, 0, 1) for dj in (-1, 0, 1)
                   for q in self.cells.get((i + di, j + dj), ()))


def trace(start, direction, field, area, laid, gap):
    """Stromlinie von start in eine Richtung (Mittelpunktsverfahren), bis Rand, Feldbruch oder Nachbarbahn."""
    import shapely
    step = 0.5 * gap
    pts, p, prev = [start], start, direction
    for _ in range(int(200 * gap / step)):
        h1 = field(p, prev)
        h2 = None if h1 is None else field(p + 0.5 * step * h1, h1)
        if h2 is None:
            break
        q = p + step * h2
        if not shapely.contains_xy(area, q[0], q[1]) or laid.near(q, 0.6 * gap):
            break
        pts.append(q)
        p, prev = q, h2
    return np.array(pts)


def streamlines(area, gap, field):
    """Fuellbahnen entlang der Zugrichtung nach Jobard und Lefer (1997), staerkster Zug zuerst."""
    import shapely
    if area.is_empty:
        return []
    shapely.prepare(area)
    x0, y0, x1, y1 = area.bounds
    gx, gy = np.meshgrid(np.arange(x0, x1, gap), np.arange(y0, y1, gap))
    seeds = np.column_stack([gx.ravel(), gy.ravel()])
    seeds = seeds[shapely.contains_xy(area, seeds[:, 0], seeds[:, 1])]
    seeds = seeds[np.argsort(-field.weight(seeds[:, ::-1]), kind="stable")]
    laid, out = Occupancy(gap), []
    for s in seeds:
        d0 = None if laid.near(s, gap) else field(s)
        if d0 is None:
            continue
        fwd = trace(s, d0, field, area, laid, gap)
        bwd = trace(s, -d0, field, area, laid, gap)
        P = np.vstack([bwd[::-1], fwd[1:]])
        if np.linalg.norm(np.diff(P, axis=0), axis=1).sum() >= 3 * gap:
            out.append((P, False))
            laid.add(P)
    return out


def resample(p, step):
    """Unterteilt einen Linienzug in Abschnitte <= step; doppelte Punkte fallen weg."""
    p = p[np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-6]]
    d = np.diff(p, axis=0)
    n = np.maximum(1, np.ceil(np.linalg.norm(d, axis=1) / step)).astype(int)
    seg = np.repeat(np.arange(len(d)), n)
    frac = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n) + 1) / np.repeat(n, n)
    return np.vstack([p[:1], p[seg] + d[seg] * frac[:, None]])


def order_paths(paths, start):
    """Fahrreihenfolge: immer der naechste Anfang; Ringe beginnen am naechsten Punkt."""
    out, pos = [], start
    for p, closed in paths:
        if closed:
            k = int(np.argmin(np.linalg.norm(p[:-1] - pos, axis=1)))
            p = np.vstack([p[k:-1], p[:k + 1]])
        elif np.linalg.norm(p[-1] - pos) < np.linalg.norm(p[0] - pos):
            p = p[::-1]
        out.append(p)
        pos = p[-1]
    return out
