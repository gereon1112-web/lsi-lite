"""
LSI Lite: ein Bauteil aus seinem FEM-Ergebnis (.vtu) lastoptimiert slicen; Verfahren und Grenzen im README.

    python lsi_lite.py                 die .vtu-Datei im Ordner eingabe/
    python lsi_lite.py bauteil.vtu
"""

import argparse
import itertools
import math
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.interpolate import RegularGridInterpolator
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent

# --- EINSTELLUNGEN ---

# Was der Nutzer waehlt (im Notebook das Formular).
SETTINGS = {
    "nozzle": 0.4,          # Duesendurchmesser in mm
    "layer_min": 0.1,       # duennste Schicht in mm
    "layer_max": 0.35,      # dickste Schicht in mm
    "max_tilt": 20.0,       # groesste Neigung der Schichten in Grad
    "infill": "konzentrisch",   # "konzentrisch", "zigzag" oder "explizit" (Stromlinien)
    "density": 100,         # Fuelldichte in Prozent, 0 = nur Waende
    "walls": 1,             # Anzahl Wandbahnen
    "printer": "220 x 220 (Ender-3 u. a.)",
    "material": "PLA",
    "build_dir": "auto",    # Baurichtung im FEM-Modell: +z, -z, +x, -x, +y, -y;
                            # "auto" = wie beim Beispiel, sonst +z
}

START_GCODE = """\
G21                     ; mm
G90                     ; absolute Koordinaten
M83                     ; Extruder relativ
M104 S{nozzle_temp}
M140 S{bed_temp}
G28                     ; Referenzfahrt
M190 S{bed_temp}
M109 S{nozzle_temp}
M107                    ; Luefter aus
G92 E0
G1 Z2.0 F3000           ; Reinigungslinie am linken Bettrand
G1 X5 Y20 Z0.3 F5000
G1 X5 Y{purge_end} Z0.3 F1500 E15
G1 X5.4 Y{purge_end} Z0.3 F5000
G1 X5.4 Y20 Z0.3 F1500 E15
G92 E0
G1 Z2.0 F3000
"""

END_GCODE = """\
M107
M104 S0
M140 S0
G91
G1 Z10 F600
G90
G28 X
M84
"""

# Druckbett (x, y) in mm.
PRINTERS = {
    "220 x 220 (Ender-3 u. a.)": (220.0, 220.0),
    "250 x 210 (Prusa MK3/MK4)": (250.0, 210.0),
    "256 x 256 (Bambu Lab X1/P1)": (256.0, 256.0),
    "350 x 350 (Voron 2.4 u. a.)": (350.0, 350.0),
}

# Duese, Bett in Grad C, Luefter in %, Faktor auf den Rueckzug.
MATERIALS = {
    "PLA":  (215, 60, 100, 1.0),
    "PETG": (240, 80, 40, 1.3),
    "ABS":  (250, 100, 10, 1.0),
}

# Feste Werte, wie in config.py des Originals.
GRID_DIVISIONS = 60         # Rasterweite = groesste Ausdehnung / 60
FREEDOM = 1e-2              # Restglaettung der Mittelschicht
OUTER_ITERS = 80            # Runden fuer Neigungs- und Amplitudengrenze
TILT_GROWTH = 3.0
IDW_K, IDW_POWER = 8, 2.0   # Abtastung des FEM-Ergebnisses
PERCENTILE = 90.0           # Bezug der Gewichtung (Zug, Anisotropie)
FILAMENT = 1.75
FIRST_LAYER_FLOW = 1.15
PRINT_SPEED, FIRST_LAYER_SPEED, TRAVEL_SPEED = 30.0, 15.0, 120.0
MIN_SPEED, MAX_SPEED = 5.0, 150.0
RETRACT, RETRACT_SPEED = 1.0, 40.0
Z_HOP = 0.6
FAN_OFF_LAYERS = 2
RESAMPLE = 0.5              # Punktabstand der Bahnen in mm

STRESS_FIELDS = ("Stress xx component", "Stress yy component",
                 "Stress zz component", "Stress xy component",
                 "Stress yz component", "Stress xz component")
# Beispiele: Datei und Baurichtung.
EXAMPLES = {
    "Biegebalken": ("beispiele/biegebalken.vtu", "+y"),
    "Tragwerk": ("beispiele/tragwerk.vtu", "-y"),
}
AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0),
        "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


class InputError(Exception):
    """Fehler in Eingabe oder Einstellungen; die Meldung sagt, was zu tun ist."""


# --- 1  BAUTEIL LESEN UND AUFS BETT LEGEN ---

def read_vtu(path):
    """Knoten, Spannungstensor je Knoten und Tetraeder (Eckknoten) einer VTU-Datei."""
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkObject
    from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader
    if not Path(path).is_file():
        raise InputError(f"Die Datei {path} gibt es nicht.")
    vtkObject.GlobalWarningDisplayOff()     # Fehler meldet die Pruefung unten
    reader = vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(path))
    reader.Update()
    grid = reader.GetOutput()
    if grid.GetNumberOfPoints() == 0:
        raise InputError(f"{path} laesst sich nicht als VTU-Datei lesen "
                         f"(leer oder beschaedigt). Datei erneut exportieren bzw. hochladen.")
    # VTK-Typ 10/24 = linearer/quadratischer Tetraeder, Ecken sind die ersten vier Knoten
    types = vtk_to_numpy(grid.GetCellTypes())
    start = vtk_to_numpy(grid.GetCells().GetOffsetsArray())[:-1][np.isin(types, (10, 24))]
    if len(start) == 0:
        raise InputError(
            f"Die Datei enthaelt kein Tetraedernetz (VTK-Zelltypen {sorted(set(types.tolist()))}). "
            "Das FEM-Modell muss mit Tetraedern vernetzt sein, z. B. C3D4 oder C3D10 in CalculiX.")
    tets = vtk_to_numpy(grid.GetCells().GetConnectivityArray())[start[:, None] + np.arange(4)]
    pd = grid.GetPointData()
    data = {pd.GetArrayName(i): vtk_to_numpy(pd.GetArray(i)) for i in range(pd.GetNumberOfArrays())}
    if all(n in data for n in STRESS_FIELDS):
        comp = np.column_stack([data[n] for n in STRESS_FIELDS])
    else:
        comp = next((np.asarray(a) for n, a in data.items()
                     if "stress" in n.lower() and np.ndim(a) == 2
                     and np.shape(a)[1] in (6, 9)), None)
        if comp is None:
            raise InputError(
                "Kein Spannungstensor in der Datei. Erwartet werden die sechs "
                "Felder des FreeCAD/CalculiX-Exports ('Stress xx component' usw.) "
                "oder ein Feld 'stress' mit 6 oder 9 Komponenten. Vorhanden: "
                + ", ".join(sorted(data)))
        if comp.shape[1] == 9:
            comp = comp[:, [0, 4, 8, 1, 5, 2]]
    sigma = np.empty((len(comp), 3, 3))
    for (i, j), c in zip(((0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (0, 2)), comp.T):
        sigma[:, i, j] = sigma[:, j, i] = c
    return vtk_to_numpy(grid.GetPoints().GetData()).astype(float), sigma, tets


def hull_triangles(tets):
    """Aussenhaut des Tetraedernetzes: Dreiecke, die nur zu einem Tetraeder gehoeren."""
    faces = np.vstack([tets[:, [0, 1, 2]], tets[:, [0, 1, 3]],
                       tets[:, [0, 2, 3]], tets[:, [1, 2, 3]]])
    _, first, count = np.unique(np.sort(faces, axis=1), axis=0,
                                return_index=True, return_counts=True)
    return faces[first[count == 1]]


def place_on_bed(points, sigma, build_dir, bed):
    """Dreht das Bauteil, bis die Baurichtung +z ist, und legt es mittig aufs Bett."""
    d = np.asarray(AXES[build_dir], dtype=float)
    helper = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    ex = helper - (helper @ d) * d
    ex /= np.linalg.norm(ex)
    R = np.array([ex, np.cross(d, ex), d])
    p = points @ R.T
    sigma = np.einsum("ij,njk,lk->nil", R, sigma, R)
    if np.ptp(p, axis=0).max() < 1.0:
        print("  Bauteil kleiner als 1 - vermutlich in Metern, wird mit 1000 "
              "in Millimeter umgerechnet.")
        p *= 1000.0
    lo, hi = p.min(axis=0), p.max(axis=0)
    p -= [0.5 * (lo[0] + hi[0]) - 0.5 * bed[0], 0.5 * (lo[1] + hi[1]) - 0.5 * bed[1], lo[2]]
    size = hi - lo
    if size[0] > bed[0] or size[1] > bed[1]:
        raise InputError(f"Das Bauteil ({size[0]:.0f} x {size[1]:.0f} mm) passt "
                         f"nicht aufs Bett ({bed[0]:.0f} x {bed[1]:.0f} mm). "
                         f"Andere Baurichtung oder groesseren Drucker waehlen.")
    return p, sigma


# --- INNEN ODER AUSSEN: SENKRECHTE LINIEN DURCH DIE HUELLE ---

def column_hits(hull, xs, ys):
    """Durchstosspunkte senkrechter Linien ueber dem Raster mit der Huelle: (Punktnummer, z), sortiert."""
    # leicht verschoben, damit keine Linie genau eine Kante trifft und doppelt zaehlt
    xs = xs + 1.234e-7 * (xs[1] - xs[0])
    ys = ys + 2.345e-7 * (ys[1] - ys[0])
    lo, hi = hull[:, :, :2].min(axis=1), hull[:, :, :2].max(axis=1)
    i0, i1 = np.searchsorted(xs, lo[:, 0]), np.searchsorted(xs, hi[:, 0], "right")
    j0, j1 = np.searchsorted(ys, lo[:, 1]), np.searchsorted(ys, hi[:, 1], "right")
    ni, nj = np.maximum(i1 - i0, 0), np.maximum(j1 - j0, 0)
    count = ni * nj
    t = np.repeat(np.arange(len(hull)), count)
    k = np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
    i, j = i0[t] + k % ni[t], j0[t] + k // ni[t]
    a, b, c = hull[t, 0], hull[t, 1], hull[t, 2]
    px, py = xs[i] - a[:, 0], ys[j] - a[:, 1]
    det = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    with np.errstate(divide="ignore", invalid="ignore"):
        l1 = (px * (c[:, 1] - a[:, 1]) - py * (c[:, 0] - a[:, 0])) / det
        l2 = ((b[:, 0] - a[:, 0]) * py - (b[:, 1] - a[:, 1]) * px) / det
        ok = (det != 0) & (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        z = (a[:, 2] + l1 * (b[:, 2] - a[:, 2]) + l2 * (c[:, 2] - a[:, 2]))[ok]
    pid = (j * len(xs) + i)[ok]
    order = np.lexsort((z, pid))
    return pid[order], z[order]


def depth(hits, z):
    """Senkrechter Abstand zur Huelle je Rasterpunkt auf Hoehe z: positiv innen."""
    pid, zh = hits
    n = len(z)
    if len(zh) == 0:
        return np.full(n, -np.inf)
    z0 = min(zh.min(), z.min())
    span = max(zh.max(), z.max()) - z0 + 1.0
    pos = np.searchsorted(pid * span + (zh - z0), np.arange(n) * span + (z - z0))
    start = np.searchsorted(pid, np.arange(n))
    end = np.searchsorted(pid, np.arange(n), "right")
    below = np.where(pos > start, z - zh[np.maximum(pos - 1, 0)], np.inf)
    above = np.where(pos < end, zh[np.minimum(pos, len(zh) - 1)] - z, np.inf)
    d = np.minimum(below, above)
    return np.where((pos - start) % 2 == 1, d, -d)


# --- FINITE ELEMENTE (gebraucht von 2 und 3) ---

def simplex_gradients(P):
    """Gradienten der linearen Formfunktionen und Inhalt je Dreieck/Tetraeder; P: (E, d+1, d)."""
    M = P[:, 1:] - P[:, :1]
    inner = np.linalg.inv(np.swapaxes(M, 1, 2))
    G = np.concatenate([-inner.sum(axis=1, keepdims=True), inner], axis=1)
    return G, np.abs(np.linalg.det(M)) / math.factorial(M.shape[1])


def stiffness(elems, G, coeff, n):
    """Steifigkeitsmatrix: Summe ueber die Elemente von coeff * G G^T."""
    local = coeff[:, None, None] * np.einsum("eid,ejd->eij", G, G)
    k = elems.shape[1]
    return sp.csr_matrix((local.ravel(), (np.repeat(elems, k, axis=1).ravel(),
                                          np.tile(elems, (1, k)).ravel())),
                         shape=(n, n))


# --- 2  MITTELSCHICHT IN DIE ZUGRICHTUNG LEGEN ---

def sample_tension(query, fem_points, sigma, refs):
    """Zugrichtung e1 und Ausrichtungsgewicht (0..1, nur Zug) an beliebigen Punkten."""
    # erst den Tensor mitteln, dann zerlegen: Hauptrichtungen haben kein Vorzeichen
    dist, idx = cKDTree(fem_points).query(query, k=IDW_K)
    w = 1.0 / (dist ** IDW_POWER + 1e-12)
    w /= w.sum(axis=1, keepdims=True)
    vals, vecs = np.linalg.eigh(np.einsum("mk,mkij->mij", w, sigma[idx]))
    ref_t, ref_a = refs
    weight = (np.clip(vals[:, -1] / ref_t, 0, 1) if ref_t > 0 else 0 * vals[:, -1]) \
        * (np.clip((vals[:, -1] - vals[:, -2]) / ref_a, 0, 1) if ref_a > 0 else 1.0)
    return vecs[:, :, -1], weight


def solve_bounded(S, rhs, s_lo, s_hi, rounds=12):
    """Loest S s = rhs unter s_lo <= s <= s_hi; Knoten am Anschlag werden festgehalten."""
    fixed = np.zeros(len(rhs), dtype=bool)
    val = np.zeros(len(rhs))
    for _ in range(rounds):
        free = ~fixed
        s = val.copy()
        s[free] = spla.spsolve(S[free][:, free].tocsc(),
                               rhs[free] - S[free][:, fixed] @ val[fixed])
        over = ((s < s_lo) | (s > s_hi)) & ~fixed
        if not over.any():
            return s, fixed
        fixed |= over
        val[fixed] = np.clip(s[fixed], s_lo[fixed], s_hi[fixed])
    return np.clip(s, s_lo, s_hi), fixed


def warp_mid(xy, tris, e1, weight, s_lo, s_hi, max_tilt):
    """Versatz s, der die Mittelschicht in die Zugrichtung legt (wie src/warp.py); Rueckgabe (s, Neigung)."""
    n = len(xy)
    G, area = simplex_gradients(xy[tris])
    w_typ = float(np.average(weight, weights=area))
    if w_typ < 1e-12:
        print("  Keine Zugspannung im Bauteil - die Mittelschicht bleibt eben.")
        return np.zeros(n), np.zeros(len(tris))
    rows = np.repeat(np.arange(len(tris)), 3)
    A = sp.csr_matrix((np.einsum("fij,fj->fi", G, e1[:, :2]).ravel(),
                       (rows, tris.ravel())), shape=(len(tris), n))
    AWA = A.T @ sp.diags(area * weight) @ A
    rhs = A.T @ (area * weight * e1[:, 2])
    mass = sp.diags(np.bincount(tris.ravel(), np.repeat(area / 3, 3), n))
    lam0 = FREEDOM * w_typ
    mu = lam0 / float(np.linalg.norm(np.ptp(xy, axis=0))) ** 2
    lam = np.full(len(tris), lam0)
    cap = lam0 * TILT_GROWTH ** 12
    for _ in range(OUTER_ITERS):
        S = (AWA + stiffness(tris, G, area * lam, n) + mu * mass).tocsr()
        s, fixed = solve_bounded(S, rhs, s_lo, s_hi)
        slope = np.linalg.norm(np.einsum("fij,fi->fj", G, s[tris]), axis=1)
        viol = (np.degrees(np.arctan(slope)) > max_tilt) | (fixed[tris].any(axis=1) & (lam < cap))
        if not viol.any():
            break
        lam[viol] = np.minimum(lam[viol] * TILT_GROWTH, cap)
    # Neigung eines Hoehenfelds waechst linear mit s: zulaessiger Anteil direkt
    gamma = min(1.0, math.tan(math.radians(max_tilt)) / max(slope.max(), 1e-12))
    if gamma < 1.0:
        print(f"  Neigungsgrenze haelt erst mit {gamma:.0%} des Versatzes.")
    return gamma * s, np.degrees(np.arctan(gamma * slope))


def alignment(slope_vec, e1, weight, area):
    """Anteil der Zugspannung, der in der Schicht liegt (1 = ganz), gewichtet gemittelt."""
    normal = np.column_stack([-slope_vec, np.ones(len(slope_vec))])
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    q = 1.0 - np.einsum("fi,fi->f", normal, e1) ** 2
    return float(np.average(q, weights=area * weight + 1e-30))


# --- 3  SCHICHTEN AUS DEM LAPLACE-FELD ---

# sechs Tetraeder je Quader entlang derselben Diagonale, damit Nachbarn lueckenlos passen
KUHN = np.array([[[0, 0, 0]] + [list(np.sum([np.eye(3, dtype=int)[a] for a in p[:m]], axis=0))
                                for m in (1, 2, 3)]
                 for p in itertools.permutations(range(3))])


def laplace_layers(xs, ys, lo, hi, levels, cell):
    """Isoflaechen u = levels des Laplace-Felds (u = 0 auf lo, 1 auf hi) als Hoehenfelder, Saeulennetz."""
    ny, nx = lo.shape
    nz = max(4, int(math.ceil(float(np.mean(hi - lo)) / (0.5 * cell))))
    Z = lo + np.linspace(0.0, 1.0, nz + 1)[:, None, None] * (hi - lo)
    X, Y = np.broadcast_to(xs, Z.shape), np.broadcast_to(ys[:, None], Z.shape)
    pts = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    base = np.arange(Z.size).reshape(Z.shape)[:-1, :-1, :-1].ravel()
    offset = KUHN[..., 2] * ny * nx + KUHN[..., 1] * nx + KUHN[..., 0]
    tets = (base[:, None, None] + offset[None]).reshape(-1, 4)
    G, vol = simplex_gradients(pts[tets])
    K = stiffness(tets, G, vol, len(pts))
    u = np.zeros(len(pts))
    u[-ny * nx:] = 1.0
    free = np.zeros(len(pts), dtype=bool)
    free[ny * nx:-ny * nx] = True
    u[free] = spla.spsolve(K[free][:, free].tocsc(), -K[free][:, ~free] @ u[~free])
    U = u.reshape(Z.shape)
    if (np.diff(U, axis=0) <= 0).any():
        raise RuntimeError("Das Feld u steigt nicht in jeder Saeule an - die "
                           "Schichten waeren nicht eindeutig. Bitte melden.")
    out = []
    for level in levels:
        k = np.clip((U < level).sum(axis=0), 1, nz)[None]
        u0, u1 = np.take_along_axis(U, k - 1, 0)[0], np.take_along_axis(U, k, 0)[0]
        z0, z1 = np.take_along_axis(Z, k - 1, 0)[0], np.take_along_axis(Z, k, 0)[0]
        out.append(z0 + (level - u0) / (u1 - u0) * (z1 - z0))
    return np.array(out)


# --- 4  SCHICHT AM BAUTEIL ABSCHNEIDEN, 5  BAHNEN ---

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
    """Waende und Fuellung einer Schicht in der Draufsicht: Liste (Punkte, geschlossen)."""
    paths = [(r, True) for i in range(cfg["walls"]) for r in rings(region.buffer(-(i + 0.5) * w))]
    density = 100 if k == 0 else cfg["density"]
    if density <= 0:
        return paths
    gap = w * 100.0 / density
    inset = cfg["walls"] * w + 0.5 * w
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
        e1, weight = sample_tension(pts, fem_points, sigma, refs)
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


# --- 6  G-CODE ---

def bead_area(h, w):
    """Querschnitt einer Bahn: Rechteck mit runden Flanken (wie PrusaSlicer und Cura)."""
    h = np.minimum(h, w)
    return (w - h) * h + math.pi * h * h / 4


class GcodeWriter:
    """Schreibt Bahnen als G-Code; Leerfahrten heben ueber die aktuelle Schicht."""

    def __init__(self, w, h_nom, retract):
        self.lines, self.pos, self.w, self.retract = [], None, w, retract
        self.flow = bead_area(h_nom, w)
        self.filament = math.pi * FILAMENT ** 2 / 4
        self.e_total = 0.0

    def travel(self, target, surface):
        """Leerfahrt mit Rueckzug, ueber die hoechste Stelle der Schicht auf dem Weg."""
        if self.pos is None:
            self.lines += [f"G0 X{target[0]:.3f} Y{target[1]:.3f} F{TRAVEL_SPEED * 60:.0f}",
                           f"G0 Z{target[2]:.3f}"]
        else:
            t = np.linspace(0, 1, 12)[:, None]
            way = self.pos[:2] + t * (target[:2] - self.pos[:2])
            z_safe = max(surface(way).max(), self.pos[2], target[2]) + Z_HOP
            self.lines += [f"G1 E{-self.retract:.3f} F{RETRACT_SPEED * 60:.0f}",
                           f"G0 Z{z_safe:.3f} F{TRAVEL_SPEED * 60:.0f}",
                           f"G0 X{target[0]:.3f} Y{target[1]:.3f}",
                           f"G0 Z{target[2]:.3f}",
                           f"G1 E{self.retract:.3f} F{RETRACT_SPEED * 60:.0f}"]
        self.pos = target

    def extrude(self, P, thickness, speed, flow):
        """Faehrt P (n, 3) ab; Menge = Querschnitt * Laenge in der Draufsicht (stimmt je Saeule)."""
        h = 0.5 * (thickness[1:] + thickness[:-1])
        area = bead_area(h, self.w)
        len_xy = np.linalg.norm(np.diff(P[:, :2], axis=0), axis=1)
        len_3d = np.linalg.norm(np.diff(P, axis=0), axis=1)
        e = area * len_xy / self.filament * flow
        # gleichmaessiger Volumenstrom: duenne Stellen schneller, dicke langsamer
        feed = np.clip(speed * self.flow / area * len_3d / np.maximum(len_xy, 1e-9),
                       MIN_SPEED, MAX_SPEED)
        self.lines += [f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f} E{de:.5f} F{f * 60:.0f}"
                       for (x, y, z), de, f in zip(P[1:], e, feed)]
        self.e_total += float(e.sum())
        self.pos = P[-1]


# --- GESAMTABLAUF ---

def check_settings(cfg):
    """Prueft die Einstellungen; Rueckgabe: Bahnbreite und Schichthoehe in der Mitte des Fensters."""
    if cfg["printer"] not in PRINTERS or cfg["material"] not in MATERIALS:
        raise InputError(f"Drucker oder Material unbekannt. Drucker: {list(PRINTERS)}, "
                         f"Material: {list(MATERIALS)}.")
    if cfg["build_dir"] not in AXES and cfg["build_dir"] != "auto":
        raise InputError(f"Baurichtung {cfg['build_dir']!r} - erlaubt: {', '.join(AXES)}.")
    if cfg["infill"] not in ("konzentrisch", "zigzag", "explizit"):
        raise InputError("Fuellung muss 'konzentrisch', 'zigzag' oder 'explizit' sein.")
    if not 0 < cfg["layer_min"] < cfg["layer_max"] <= cfg["nozzle"]:
        raise InputError("Schichthoehe: es muss gelten 0 < min < max <= Duesendurchmesser.")
    if not 0 < cfg["max_tilt"] <= 45 or not 0 <= cfg["density"] <= 100 or cfg["walls"] < 0:
        raise InputError("Neigung 0..45 Grad, Fuelldichte 0..100 %, Waende >= 0.")
    h_nom = 0.5 * (cfg["layer_min"] + cfg["layer_max"])
    thinned = h_nom * math.cos(math.radians(cfg["max_tilt"]))
    if thinned <= cfg["layer_min"]:
        raise InputError(f"Bei {cfg['max_tilt']:.0f} Grad Neigung ist die Schicht nur "
                         f"{thinned:.3f} mm dick (Fenster ab {cfg['layer_min']:.3f} mm). "
                         f"Neigung senken oder kleinste Schichthoehe verringern.")
    return cfg["nozzle"] + cfg["layer_max"], h_nom


def slice_vtu(vtu, out_dir=None, **settings):
    """Rechnet den G-Code; Rueckgabe (G-Code, Vorschaubild, Bahnen je Schicht, Zugstriche)."""
    cfg = {**SETTINGS, **settings}
    w, h_nom = check_settings(cfg)
    vtu = Path(vtu)
    out_dir = Path(out_dir) if out_dir else vtu.parent
    bed = PRINTERS[cfg["printer"]]
    if cfg["build_dir"] == "auto":
        cfg["build_dir"] = next((d for f, d in EXAMPLES.values() if Path(f).name == vtu.name), "+z")
        print(f"Baurichtung {cfg['build_dir']} (automatisch)")

    print("1  Bauteil lesen")
    fem_pts, sigma, tets = read_vtu(vtu)
    fem_pts, sigma = place_on_bed(fem_pts, sigma, cfg["build_dir"], bed)
    hull = fem_pts[hull_triangles(tets)]
    height = float(fem_pts[:, 2].max())
    lo, hi = fem_pts[:, :2].min(axis=0), fem_pts[:, :2].max(axis=0)
    cell = max(np.ptp(fem_pts, axis=0).max() / GRID_DIVISIONS, w)
    xs = np.linspace(lo[0], hi[0], int(math.ceil((hi[0] - lo[0]) / cell)) + 1)
    ys = np.linspace(lo[1], hi[1], int(math.ceil((hi[1] - lo[1]) / cell)) + 1)
    nx, ny = len(xs), len(ys)
    print(f"   {len(fem_pts)} FEM-Knoten, Bauteil {hi[0] - lo[0]:.1f} x {hi[1] - lo[1]:.1f}"
          f" x {height:.1f} mm, Raster {nx} x {ny} ({cell:.2f} mm)")

    print("2  Mittelschicht in die Zugrichtung legen")
    # Quader wie im Original: doppelte Bauteilhoehe, Mittelschicht mittig, Bett unten
    z_mid, z_top = 0.5 * height, 1.5 * height
    xy = np.column_stack([np.tile(xs, ny), np.repeat(ys, nx)])
    idx = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    tris = np.vstack([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
    vals = np.linalg.eigvalsh(sigma)
    refs = (float(np.percentile(np.clip(vals[:, -1], 0, None), PERCENTILE)),
            float(np.percentile(np.clip(vals[:, -1] - vals[:, -2], 0, None), PERCENTILE)))
    cent = xy[tris].mean(axis=1)
    e1, weight = sample_tension(np.column_stack([cent, np.full(len(cent), z_mid)]),
                                fem_pts, sigma, refs)
    hits = column_hits(hull, xs, ys)
    inside = np.clip(depth(hits, np.full(nx * ny, z_mid)) / cell, 0, 1)
    weight *= inside[tris].mean(axis=1)
    # Amplitudengrenze aus dem Schichthoehenfenster (src/printability.py)
    thick = cfg["layer_max"] / h_nom - 1
    thin = 1 - cfg["layer_min"] / (h_nom * math.cos(math.radians(cfg["max_tilt"])))
    reach_dn, reach_up = z_mid, z_top - z_mid
    s_dn = min(0.9 * reach_dn, thick * reach_up, thin * reach_dn)
    s_up = min(0.9 * reach_up, thick * reach_dn, thin * reach_up)
    s, tilt = warp_mid(xy, tris, e1, weight, np.full(nx * ny, -s_dn),
                       np.full(nx * ny, s_up), cfg["max_tilt"])
    G, area = simplex_gradients(xy[tris])
    q0 = alignment(np.zeros((len(tris), 2)), e1, weight, area)
    q1 = alignment(np.einsum("fij,fi->fj", G, s[tris]), e1, weight, area)
    print(f"   Versatz {s.min():.2f} .. {s.max():.2f} mm, Neigung max {tilt.max():.1f} Grad, "
          f"Zug in der Schicht {q0:.0%} -> {q1:.0%}")
    mid = z_mid + s.reshape(ny, nx)

    print("3  Schichten aus dem Laplace-Feld")
    n_dn = max(1, round(float(mid.mean()) / h_nom))
    n_up = max(1, round(float((z_top - mid).mean()) / h_nom))
    layers = np.concatenate([
        laplace_layers(xs, ys, np.zeros_like(mid), mid, np.arange(1, n_dn + 1) / n_dn, cell),
        laplace_layers(xs, ys, mid, np.full_like(mid, z_top), np.arange(1, n_up + 1) / n_up, cell)])
    layers = layers[layers.min(axis=(1, 2)) < height]

    print("4  Schichten abschneiden, 5  Bahnen")
    step = 0.5 * w
    fx = np.arange(lo[0] - step, hi[0] + 2 * step, step)
    fy = np.arange(lo[1] - step, hi[1] + 2 * step, step)
    fine = np.stack(np.meshgrid(fy, fx, indexing="ij"), axis=-1).reshape(-1, 2)
    fine_hits = column_hits(hull, fx, fy)
    printed, below, h_rng, pos = [], np.zeros((ny, nx)), [np.inf, 0.0], np.zeros(2)
    support, loose = None, []
    for k, layer in enumerate(layers):
        surf = RegularGridInterpolator((ys, xs), layer, bounds_error=False, fill_value=None)
        dz = RegularGridInterpolator((ys, xs), layer - below, bounds_error=False, fill_value=None)
        dist = np.clip(depth(fine_hits, surf(fine)), -step, step).reshape(len(fy), len(fx))
        region = outline(fx, fy, dist).simplify(0.05 * w)
        below = layer
        if region.area < w * w:
            continue
        # Ueberhang: Flaeche, die nicht auf der Schicht darunter liegt
        if support is not None:
            loose.append(region.difference(support.buffer(0.5 * w)).area / region.area)
        support = region
        field = (DirectionField(xs, ys, layer, fem_pts, sigma, refs)
                 if cfg["infill"] == "explizit" else None)
        ordered = order_paths(layer_paths(region, len(printed), cfg, w, field), pos)
        paths = []
        for p in ordered:
            p = resample(p, RESAMPLE)
            yx = p[:, ::-1]
            paths.append((np.column_stack([p, surf(yx)]), dz(yx)))
        pos = ordered[-1][-1] if ordered else pos
        slope = np.degrees(np.arctan(np.hypot(*np.gradient(layer, ys, xs))))
        inside_k = depth(hits, layer.ravel()).reshape(ny, nx) > 0
        if inside_k.any():
            # 5./95. Perzentil je Schicht wie im Original
            h_n = ((layer - layers[k - 1] if k else layer) * np.cos(np.radians(slope)))[inside_k]
            h_rng = [min(h_rng[0], np.percentile(h_n, 5)), max(h_rng[1], np.percentile(h_n, 95))]
        printed.append((paths, surf))
    if not printed:
        raise InputError("Keine Schicht schneidet das Bauteil - ist die Datei leer?")
    print(f"   {len(printed)} Schichten, Dicke (senkrecht zur Schicht) "
          f"{h_rng[0]:.3f} .. {h_rng[1]:.3f} mm, Bahnbreite {w:.2f} mm")
    if h_rng[0] < 0.95 * cfg["layer_min"] or h_rng[1] > 1.05 * cfg["layer_max"]:
        print(f"   ACHTUNG: Schichtdicke ausserhalb des Fensters "
              f"{cfg['layer_min']} .. {cfg['layer_max']} mm.")
    n_loose = sum(f > 0.05 for f in loose)
    if n_loose:
        print(f"   ACHTUNG: Ueberhang - in {n_loose} Schichten liegen bis zu {max(loose):.0%} "
              f"der Flaeche frei in der Luft. Ohne Stuetzen nicht druckbar; "
              f"andere Baurichtung waehlen.")

    print("6  G-Code")
    nozzle_temp, bed_temp, fan, retract = MATERIALS[cfg["material"]]
    gc = GcodeWriter(w, h_nom, RETRACT * retract)
    gc.lines += [f"; LSI Lite - {vtu.name}",
                 "; " + ", ".join(f"{k}={v}" for k, v in cfg.items()),
                 START_GCODE.format(nozzle_temp=nozzle_temp, bed_temp=bed_temp,
                                    purge_end=min(200, bed[1] - 20))]
    for k, (paths, surf) in enumerate(printed):
        gc.lines.append(f";LAYER:{k}")
        if k == FAN_OFF_LAYERS:
            gc.lines.append(f"M106 S{round(2.55 * fan)}")
        for P, t in paths:
            gc.travel(P[0], lambda q, s=surf: s(q[:, ::-1]))
            gc.extrude(P, t, FIRST_LAYER_SPEED if k == 0 else PRINT_SPEED,
                       FIRST_LAYER_FLOW if k == 0 else 1.0)
    gc.lines.append(END_GCODE)
    out_dir.mkdir(parents=True, exist_ok=True)
    gcode = out_dir / f"{vtu.stem}_lite.gcode"
    gcode.write_text("\n".join(gc.lines) + "\n", encoding="utf-8")
    meters = gc.e_total / 1000
    print(f"   {gcode.name}: {len(gc.lines)} Zeilen, Filament {meters:.1f} m "
          f"(etwa {meters * 2.98:.0f} g PLA)")
    png = out_dir / f"{vtu.stem}_lite.png"
    strokes = tension_strokes(fem_pts, sigma, 2 * cell)
    preview(xs, ys, layers, mid, hits, strokes, cell, png)
    return gcode, png, [[P for P, _ in paths] for paths, _ in printed], strokes


def tension_strokes(points, sigma, length):
    """Striche in Richtung sigma_1 an FEM-Knoten ab 5 % Zug, Laenge gestaucht mit dem Betrag; (n, 2, 3)."""
    vals, vecs = np.linalg.eigh(sigma)
    if not (vals[:, -1] > 0).any():
        return np.empty((0, 2, 3))
    ref = np.percentile(vals[vals[:, -1] > 0, -1], 95)
    tension = vals[:, -1] > 0.05 * ref
    s1 = vals[tension, -1]
    half = 0.5 * length * np.minimum(s1 / ref, 1.0) ** 0.4
    e = vecs[tension, :, -1] * half[:, None]
    return np.stack([points[tension] - e, points[tension] + e], axis=1)


def show_paths(layer_paths, upto=None, strokes=None, max_points=300_000, max_strokes=2000):
    """Drehbare 3D-Ansicht der Bahnen bis Schicht upto, optional mit Zugstrichen; duennt fuer den Browser aus."""
    import plotly.graph_objects as go
    shown = layer_paths[:upto]
    total = sum(len(P) for paths in shown for P in paths)
    step = max(1, -(-total // max_points))
    xyz, color = [], []
    for k, paths in enumerate(shown):
        for P in paths:
            pts = np.vstack([P[::step], P[-1:], [[np.nan] * 3]])
            xyz.append(pts)
            color.append(np.full(len(pts), k))
    xyz, color = np.vstack(xyz), np.concatenate(color)
    fig = go.Figure(go.Scatter3d(
        x=xyz[:, 0], y=xyz[:, 1], z=xyz[:, 2], mode="lines", name="Bahnen",
        line=dict(color=color, colorscale="Turbo", width=2,
                  colorbar=dict(title="Schicht", x=1.0))))
    if strokes is not None and len(strokes):
        s = strokes[strokes[:, :, 2].mean(axis=1) <= np.nanmax(xyz[:, 2])]
        s = s[::max(1, len(s) // max_strokes)]
        s = np.concatenate([s, np.full((len(s), 1, 3), np.nan)], axis=1).reshape(-1, 3)
        fig.add_trace(go.Scatter3d(x=s[:, 0], y=s[:, 1], z=s[:, 2], mode="lines",
                                   name="Zugrichtung (sigma_1)", line=dict(color="black", width=3)))
    fig.update_layout(scene=dict(aspectmode="data", xaxis_title="x", yaxis_title="y",
                                 zaxis_title="z"),
                      margin=dict(l=0, r=0, t=30, b=0), height=600,
                      legend=dict(x=0, y=1),
                      title=f"Bahnen der Schichten 1 bis {len(shown)}"
                            + (f" (jeder {step}. Punkt)" if step > 1 else ""))
    return fig


def preview(xs, ys, layers, mid, hits, strokes, cell, png):
    """Vorschaubild: Schnitt durch Schichten und Zugrichtung, Auslenkung der Mittelschicht."""
    import matplotlib
    if "ipykernel" not in sys.modules:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    j = len(ys) // 2
    row = (hits[0] // len(xs) == j)
    row_hits = (hits[0][row] % len(xs), hits[1][row])
    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 4.2),
                                      gridspec_kw={"width_ratios": [1.6, 1]})
    every = max(1, len(layers) // 40)
    for layer in layers[::every]:
        z = layer[j]
        left.plot(xs, np.where(depth(row_hits, z) > 0, z, np.nan), color="0.45", lw=0.6)
    left.plot(xs, np.where(depth(row_hits, mid[j]) > 0, mid[j], np.nan), color="C3", lw=2,
              label="Mittelschicht")
    near = strokes[np.abs(strokes[:, :, 1].mean(axis=1) - ys[j]) < 0.5 * cell]
    near = near[::max(1, -(-len(near) // 200))]
    centre = near.mean(axis=1, keepdims=True)
    left.add_collection(LineCollection((centre + 0.5 * (near - centre))[:, :, [0, 2]],
                                       colors="C0", linewidths=1.0, label="Zugrichtung (sigma_1)"))
    left.set(title=f"Schnitt bei y = {ys[j]:.1f} mm (jede {every}. Schicht)",
             xlabel="x in mm", ylabel="z in mm", aspect="equal")
    left.legend(loc="upper center", bbox_to_anchor=(0.5, -0.42), ncol=2, frameon=False)
    im = right.imshow(mid - mid.mean(), origin="lower", cmap="coolwarm",
                      extent=(xs[0], xs[-1], ys[0], ys[-1]))
    right.set(title="Auslenkung der Mittelschicht", xlabel="x in mm", ylabel="y in mm")
    fig.colorbar(im, ax=right, label="mm", location="bottom", shrink=0.8)
    fig.tight_layout()
    fig.savefig(png, dpi=130)
    if "ipykernel" in sys.modules:
        plt.show()
    plt.close(fig)


def default_input():
    """Die .vtu-Datei im Ordner eingabe/ neben diesem Programm (bei mehreren die neueste)."""
    found = sorted((HERE / "eingabe").glob("*.vtu"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise InputError("Keine Eingabe: Lege eine .vtu-Datei in den Ordner "
                         f"{HERE / 'eingabe'} oder starte mit\n"
                         "    python lsi_lite.py pfad/zum/bauteil.vtu")
    if len(found) > 1:
        print(f"Mehrere .vtu-Dateien in eingabe/, genommen wird die neueste: {found[-1].name}")
    return found[-1]


def main():
    """Startet LSI Lite von der Kommandozeile, ohne Argument mit der Datei aus eingabe/."""
    parser = argparse.ArgumentParser(description="LSI Lite: lastoptimiert slicen aus einer .vtu-Datei. "
                                                 "Einstellungen stehen oben in SETTINGS.")
    parser.add_argument("vtu", nargs="?", help="FEM-Ergebnis (Vorgabe: die Datei in eingabe/)")
    args = parser.parse_args()
    try:
        gcode, png, _, _ = slice_vtu(Path(args.vtu) if args.vtu else default_input())
    except InputError as err:
        sys.exit(f"Abbruch: {err}")
    print(f"Fertig: {gcode}\n        {png}")


if __name__ == "__main__":
    main()
