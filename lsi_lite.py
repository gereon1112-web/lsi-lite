"""LSI Lite: Ablauf vom FEM-Ergebnis (.vtu) zum G-Code; die Schritte stehen in bausteine/, gestartet wird im Notebook."""

import math
from pathlib import Path

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from bausteine import ansicht, bahnen, bauteil, gcode, schichten
from bausteine.ansicht import show_paths  # noqa: F401  (fuers Notebook)
from bausteine.bauteil import InputError
from bausteine.config import (END_GCODE, EXAMPLES, FAN_OFF_LAYERS, FIRST_LAYER_FLOW, FIRST_LAYER_SPEED,
                              GRID_DIVISIONS, LAYER_RATIO, MATERIALS, MID_DAMPING, MID_STAGES, PERCENTILE,
                              PRINT_SPEED, PRINTERS, RESAMPLE, RETRACT, START_GCODE)

HERE = Path(__file__).resolve().parent


def slice_vtu(vtu, show, **cfg):
    """Rechnet den G-Code; Rueckgabe (G-Code-Datei, Bahnen je Schicht, Zugstriche, Mittelschicht).

    show bekommt die Schrittliste als HTML; cfg sind die Einstellungen aus dem Notebook-Formular.
    """
    if not 0.1 <= cfg["nozzle"] <= 2.0:
        raise InputError("Duesendurchmesser 0.1 .. 2.0 mm.")
    h_min, h_max = LAYER_RATIO[0] * cfg["nozzle"], LAYER_RATIO[1] * cfg["nozzle"]
    h_nom, w = 0.5 * (h_min + h_max), cfg["nozzle"] + h_max
    vtu = Path(vtu)
    progress = ansicht.Progress(vtu.name, show)
    bed = PRINTERS[cfg["printer"]]
    if cfg["build_dir"] == "auto":
        cfg["build_dir"] = next((d for f, d in EXAMPLES.values() if Path(f).name == vtu.name), "+z")
    progress.step(0)
    fem_pts, sigma, tets = bauteil.read_vtu(vtu)
    fem_pts, sigma = bauteil.place_on_bed(fem_pts, sigma, cfg["build_dir"], bed, progress.warn)
    hull = fem_pts[bauteil.hull_triangles(tets)]
    height = float(fem_pts[:, 2].max())
    lo, hi = fem_pts[:, :2].min(axis=0), fem_pts[:, :2].max(axis=0)
    cell = max(np.ptp(fem_pts, axis=0).max() / GRID_DIVISIONS, w)
    xs = np.linspace(lo[0], hi[0], int(math.ceil((hi[0] - lo[0]) / cell)) + 1)
    ys = np.linspace(lo[1], hi[1], int(math.ceil((hi[1] - lo[1]) / cell)) + 1)
    nx, ny = len(xs), len(ys)
    progress.note(f"Bauteil {hi[0] - lo[0]:.0f} x {hi[1] - lo[1]:.0f} x {height:.0f} mm, Baurichtung "
                  f"{cfg['build_dir']}, {len(fem_pts)} FEM-Knoten, Raster {nx} x {ny}")

    progress.step(1)
    # Quader doppelt so hoch wie das Bauteil, Bauteil mittig; das Bett schneidet die Schichten nur ab
    z_bot, z_mid, z_top = -0.5 * height, 0.5 * height, 1.5 * height
    xy = np.column_stack([np.tile(xs, ny), np.repeat(ys, nx)])
    idx = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    tris = np.vstack([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
    vals = np.linalg.eigvalsh(sigma)
    refs = (float(np.percentile(np.clip(vals[:, -1], 0, None), PERCENTILE)),
            float(np.percentile(np.clip(vals[:, -1] - vals[:, -2], 0, None), PERCENTILE)))
    hits = bauteil.column_hits(hull, xs, ys)
    G, area = schichten.simplex_gradients(xy[tris])
    # groesster Versatz, bei dem die Schichten darueber und darunter im Hoehenfenster bleiben
    thick = h_max / h_nom - 1
    thin = 1 - h_min / (h_nom * math.cos(math.radians(cfg["max_tilt"])))
    amp = height * min(0.9, thick, thin)
    s_lo, s_hi = np.full(nx * ny, -amp), np.full(nx * ny, amp)
    # Zugrichtung je Stufe an der verformten Flaeche neu abtasten, gedaempft gegen Hin- und Herspringen
    s = np.zeros(nx * ny)
    for stage in range(1, MID_STAGES + 1):
        progress.step(1, f"Stufe {stage} von {MID_STAGES}", (stage - 1) / MID_STAGES)
        e1, weight = schichten.tension_on_surface(xy, tris, z_mid + s, fem_pts, sigma, refs, hits, cell)
        if stage == 1:
            q0 = schichten.alignment(np.zeros((len(tris), 2)), e1, weight, area)
        s_new, tilt = schichten.warp_mid(xy, tris, e1, weight, s_lo, s_hi, cfg["max_tilt"], progress.warn)
        if np.abs(s_new - s).max() < 1e-3 * height:
            break
        s += MID_DAMPING * (s_new - s)
    s = s_new
    e1, weight = schichten.tension_on_surface(xy, tris, z_mid + s, fem_pts, sigma, refs, hits, cell)
    q1 = schichten.alignment(np.einsum("fij,fi->fj", G, s[tris]), e1, weight, area)
    progress.note(f"Zug in der Schicht {q0:.0%} -> {q1:.0%}, Neigung max {tilt.max():.1f} Grad, "
                  f"Versatz {s.min():.1f} .. {s.max():.1f} mm")
    mid = z_mid + s.reshape(ny, nx)

    progress.step(2, "unter der Mittelschicht", 0.0)
    n_dn = max(1, round(float((mid - z_bot).mean()) / h_nom))
    n_up = max(1, round(float((z_top - mid).mean()) / h_nom))
    below_mid = schichten.laplace_layers(xs, ys, np.full_like(mid, z_bot), mid, np.arange(1, n_dn + 1) / n_dn, cell)
    progress.step(2, "ueber der Mittelschicht", 0.5)
    above_mid = schichten.laplace_layers(xs, ys, mid, np.full_like(mid, z_top), np.arange(1, n_up + 1) / n_up, cell)
    layers = np.concatenate([below_mid, above_mid])
    layers = layers[(layers.min(axis=(1, 2)) < height) & (layers.max(axis=(1, 2)) > 0)]

    progress.step(3)
    step = 0.5 * w
    fx = np.arange(lo[0] - step, hi[0] + 2 * step, step)
    fy = np.arange(lo[1] - step, hi[1] + 2 * step, step)
    fine = np.stack(np.meshgrid(fy, fx, indexing="ij"), axis=-1).reshape(-1, 2)
    fine_hits = bauteil.column_hits(hull, fx, fy)
    distance_to_hull = bauteil.hull_distance(hull)
    printed, below, h_rng, pos = [], np.zeros((ny, nx)), [np.inf, 0.0], np.zeros(2)
    for k, layer in enumerate(layers):
        progress.step(3, f"Schicht {k + 1} von {len(layers)}", k / len(layers))
        # jeder Punkt h_min (senkrecht zur Schicht) bis h_max ueber dem Bett oder der letzten Schicht
        stretch = np.hypot(1.0, np.hypot(*np.gradient(layer, ys, xs)))
        fits = np.clip(layer, below + h_min * stretch, below + h_max)
        thick_k = fits - below
        surf = RegularGridInterpolator((ys, xs), fits, bounds_error=False, fill_value=None)
        dz = RegularGridInterpolator((ys, xs), thick_k, bounds_error=False, fill_value=None)
        inside = RegularGridInterpolator((ys, xs), layer, bounds_error=False, fill_value=None)
        z_fine = inside(fine)
        dist = np.clip(bauteil.depth(fine_hits, z_fine), -step, step).reshape(len(fy), len(fx))
        dist = bauteil.exact_at_edge(dist, np.column_stack([fine[:, ::-1], z_fine]), distance_to_hull, step)
        region = bahnen.outline(fx, fy, dist).simplify(0.05 * w)
        below = np.where(layer > below, fits, below)
        if region.area < w * w:
            continue
        field = (bahnen.DirectionField(xs, ys, fits, fem_pts, sigma, refs)
                 if cfg["infill"] == "explizit" else None)
        ordered = bahnen.order_paths(bahnen.layer_paths(region, len(printed), cfg, w, field), pos)
        paths = []
        for p in ordered:
            p = bahnen.resample(p, RESAMPLE)
            yx = p[:, ::-1]
            paths.append((np.column_stack([p, surf(yx)]), dz(yx)))
        pos = ordered[-1][-1] if ordered else pos
        inside_k = bauteil.depth(hits, layer.ravel()).reshape(ny, nx) > 0
        if inside_k.any():
            h_n = (thick_k / stretch)[inside_k]
            h_rng = [min(h_rng[0], np.percentile(h_n, 5)), max(h_rng[1], np.percentile(h_n, 95))]
        printed.append((paths, surf))
    if not printed:
        raise InputError("Keine Schicht schneidet das Bauteil - ist die Datei leer?")
    progress.note(f"{len(printed)} Schichten, Dicke senkrecht zur Schicht "
                  f"{h_rng[0]:.2f} .. {h_rng[1]:.2f} mm")

    progress.step(4)
    nozzle_temp, bed_temp, fan, retract = MATERIALS[cfg["material"]]
    gc = gcode.GcodeWriter(w, h_nom, RETRACT * retract)
    gc.lines += [f"; LSI Lite - {vtu.name}",
                 "; " + ", ".join(f"{k}={v}" for k, v in cfg.items()),
                 START_GCODE.format(nozzle_temp=nozzle_temp, bed_temp=bed_temp,
                                    purge_end=min(200, bed[1] - 20))]
    for k, (paths, surf) in enumerate(printed):
        progress.step(4, f"Schicht {k + 1} von {len(printed)}", k / len(printed))
        gc.lines.append(f";LAYER:{k}")
        if k == FAN_OFF_LAYERS:
            gc.lines.append(f"M106 S{round(2.55 * fan)}")
        for P, t in paths:
            gc.travel(P[0], lambda q, s=surf: s(q[:, ::-1]))
            gc.extrude(P, t, FIRST_LAYER_SPEED if k == 0 else PRINT_SPEED,
                       FIRST_LAYER_FLOW if k == 0 else 1.0)
    gc.lines.append(END_GCODE)
    out_file = vtu.with_name(f"{vtu.stem}_lite.gcode")
    out_file.write_text("\n".join(gc.lines) + "\n", encoding="utf-8")
    meters = gc.e_total / 1000
    progress.note(f"Filament {meters:.1f} m (etwa {meters * 2.98:.0f} g PLA), Druckzeit etwa "
                  f"{gc.seconds / 60:.0f} min (ohne Beschleunigung)")
    progress.step(len(ansicht.STEPS))
    strokes = ansicht.tension_strokes(fem_pts, sigma, 2 * cell)
    # Mittelschicht fuer die Ansicht: feines Raster, ausserhalb des Bauteils NaN
    mid_f = RegularGridInterpolator((ys, xs), mid, bounds_error=False, fill_value=None)(fine)
    mid_in = np.where(bauteil.depth(fine_hits, mid_f) > 0, mid_f, np.nan).reshape(len(fy), len(fx))
    return out_file, [[P for P, _ in paths] for paths, _ in printed], strokes, (fx, fy, mid_in)


def default_input():
    """Die .vtu-Datei im Ordner eingabe/ (bei mehreren die neueste)."""
    found = sorted((HERE / "eingabe").glob("*.vtu"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise InputError(f"Keine Eingabe: Lege eine .vtu-Datei in den Ordner {HERE / 'eingabe'}.")
    if len(found) > 1:
        print(f"Mehrere .vtu-Dateien in eingabe/, genommen wird die neueste: {found[-1].name}")
    return found[-1]


if __name__ == "__main__":
    print("LSI Lite wird ueber das Notebook LSI_lite.ipynb gestartet.")
