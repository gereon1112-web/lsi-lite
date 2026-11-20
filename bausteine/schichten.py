"""Die Schichtflaechen: Mittelschicht in die Zugrichtung legen, Schichten darueber und darunter."""

import itertools
import math

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from bausteine import bauteil
from bausteine.config import FREEDOM, MID_SMOOTHING, OUTER_ITERS, TILT_GROWTH


# --- FINITE ELEMENTE ---

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

def tension_on_surface(xy, tris, z, fem_points, sigma, refs, hits, cell):
    """Zugrichtung und Gewicht je Dreieck der Flaeche mit Knotenhoehen z; ausserhalb des Bauteils Gewicht 0."""
    cent = np.column_stack([xy[tris].mean(axis=1), z[tris].mean(axis=1)])
    e1, weight = bauteil.sample_tension(cent, fem_points, sigma, refs)
    inside = np.clip(bauteil.depth(hits, z) / cell, 0, 1)
    return e1, weight * inside[tris].mean(axis=1)


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


def warp_mid(xy, tris, e1, weight, s_lo, s_hi, max_tilt, warn):
    """Versatz s, der die Mittelschicht in die Zugrichtung legt; Rueckgabe (s, Neigung je Dreieck)."""
    n = len(xy)
    G, area = simplex_gradients(xy[tris])
    w_typ = float(np.average(weight, weights=area))
    if w_typ < 1e-12:
        warn("Keine Zugspannung im Bauteil - die Mittelschicht bleibt eben.")
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
    # Glaetten rundet die Knicke ab, wo von der Neigungsgrenze versteifte Dreiecke an weiche grenzen
    smooth = mass + MID_SMOOTHING * 2.0 * float(area.mean()) * stiffness(tris, G, area, n)
    s = spla.spsolve(smooth.tocsc(), mass @ s)
    slope = np.linalg.norm(np.einsum("fij,fi->fj", G, s[tris]), axis=1)
    # Neigung waechst linear mit s, der zulaessige Anteil folgt direkt
    gamma = min(1.0, math.tan(math.radians(max_tilt)) / max(slope.max(), 1e-12))
    if gamma < 1.0:
        warn(f"Neigungsgrenze haelt erst mit {gamma:.0%} des Versatzes.")
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
