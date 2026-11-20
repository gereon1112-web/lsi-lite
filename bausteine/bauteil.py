"""Das Bauteil: aus der VTU-Datei lesen, aufs Bett legen, innen/aussen und Zugrichtung abfragen."""

import numpy as np
from scipy.spatial import cKDTree

from bausteine.config import AXES, IDW_K, IDW_POWER, STRESS_FIELDS


class InputError(Exception):
    """Fehler in Eingabe oder Einstellungen; die Meldung sagt, was zu tun ist."""


# --- 1  BAUTEIL LESEN UND AUFS BETT LEGEN ---

def read_vtu(path):
    """Knoten, Spannungstensor je Knoten und Tetraeder (Eckknoten) einer VTU-Datei."""
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkObject
    from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader
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


def place_on_bed(points, sigma, build_dir, bed, warn):
    """Dreht die Baurichtung nach +z und legt das Bauteil mittig aufs Bett."""
    d = np.asarray(AXES[build_dir], dtype=float)
    helper = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    ex = helper - (helper @ d) * d
    ex /= np.linalg.norm(ex)
    R = np.array([ex, np.cross(d, ex), d])
    p = points @ R.T
    sigma = np.einsum("ij,njk,lk->nil", R, sigma, R)
    if np.ptp(p, axis=0).max() < 1.0:
        warn("Bauteil kleiner als 1 - vermutlich in Metern, wird mit 1000 in Millimeter umgerechnet.")
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


def hull_distance(hull):
    """Funktion, die fuer Punkte (n, 3) den Abstand zum naechsten Huelldreieck liefert (ohne Vorzeichen)."""
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkDoubleArray, vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    from vtkmodules.vtkFiltersCore import vtkImplicitPolyDataDistance
    points = vtkPoints()
    points.SetData(numpy_to_vtk(hull.reshape(-1, 3), deep=True))
    cells = vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(np.arange(0, 3 * len(hull) + 1, 3), deep=True),
                  numpy_to_vtkIdTypeArray(np.arange(3 * len(hull)), deep=True))
    surface = vtkPolyData()
    surface.SetPoints(points)
    surface.SetPolys(cells)
    distance = vtkImplicitPolyDataDistance()
    distance.SetInput(surface)

    def query(p):
        out = vtkDoubleArray()
        distance.FunctionValue(numpy_to_vtk(np.asarray(p, dtype=float), deep=True), out)
        return np.abs(vtk_to_numpy(out))
    return query


def exact_at_edge(d, points, distance_to_hull, limit):
    """Am Rand den echten Abstand zur Huelle statt des senkrechten, sonst werden schraege Waende treppig."""
    inside = d > 0
    edge = np.zeros(d.shape, dtype=bool)
    for flip, a, b in ((inside[:, 1:] != inside[:, :-1], np.s_[:, 1:], np.s_[:, :-1]),
                       (inside[1:] != inside[:-1], np.s_[1:], np.s_[:-1])):
        edge[a] |= flip
        edge[b] |= flip
    d = d.copy()
    d[edge] = np.where(inside[edge], 1.0, -1.0) * np.minimum(distance_to_hull(points[edge.ravel()]), limit)
    return d


# --- ZUGRICHTUNG AUS DEM FEM-ERGEBNIS ---

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
