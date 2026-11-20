"""Anzeige: Fortschritt waehrend der Rechnung und 3D-Ansicht der Bahnen."""

import time
from html import escape

import numpy as np


# --- FORTSCHRITT ---

STEPS = ("Bauteil lesen", "Mittelschicht in die Zugrichtung legen", "Schichten aus dem Laplace-Feld",
         "Schichten abschneiden, Bahnen legen", "G-Code schreiben")

PROGRESS_CSS = """<style>
.lsi{font-family:system-ui,sans-serif;max-width:600px;padding:12px 16px;border:1px solid #8884;border-radius:12px}
.lsi .r{display:flex;gap:12px;padding:4px 0} .lsi small{opacity:.65} .lsi .wait{opacity:.5}
.lsi .d{flex:0 0 22px;height:22px;line-height:22px;border-radius:50%;border:2px solid #8886;text-align:center;font-size:12px}
.lsi .ok .d{background:#2e9d5b;border-color:#2e9d5b;color:#fff}
.lsi .bad{color:#d64545} .lsi .bad .d{background:#d64545;border-color:#d64545;color:#fff}
.lsi .run .d{border-color:#3b82f6;color:#3b82f6;animation:lsi 1.4s infinite}
.lsi i{display:block;height:4px;margin-top:4px;border-radius:2px;background:#3b82f6}
@keyframes lsi{0%{box-shadow:0 0 0 0 #3b82f680}70%{box-shadow:0 0 0 7px #3b82f600}}
</style>"""


class Progress:
    """Schrittliste als HTML; show bekommt sie bei jeder Aenderung."""

    def __init__(self, title, show):
        self.title, self.show, self.current, self.starts = title, show, -1, []
        self.notes, self.warnings = {}, []

    def step(self, k, detail="", share=None):
        """Schritt k (ab 0) laeuft; detail und share (0..1) sagen, wie weit er ist."""
        if k != self.current:
            self.current = k
            self.starts.append(time.perf_counter())
        self.show(self.html(detail, share))

    def note(self, text):
        """Kurze Meldung, klein hinter dem laufenden Schritt."""
        self.notes[self.current] = text

    def warn(self, text):
        """Warnung, rot unter der Schrittliste."""
        if text not in self.warnings:
            self.warnings.append(text)

    def html(self, detail, share):
        """Schrittliste: erledigt mit Haken und Dauer, laufend mit Balken, wartend blass."""
        rows = []
        for k, name in enumerate(STEPS):
            if k < self.current:
                took = self.starts[k + 1] - self.starts[k]
                note = f"<br><small>{escape(self.notes[k])}</small>" if k in self.notes else ""
                rows.append(f'<div class="r ok"><b class="d">&#10003;</b>'
                            f'<div>{name} <small>{took:.1f} s</small>{note}</div></div>')
            elif k == self.current:
                bar = f'<i style="width:{100 * share:.0f}%"></i>' if share is not None else ""
                rows.append(f'<div class="r run"><b class="d">{k + 1}</b>'
                            f'<div style="flex:1"><b>{name}</b> <small>{detail}</small>{bar}</div></div>')
            else:
                rows.append(f'<div class="r wait"><b class="d">{k + 1}</b>{name}</div>')
        rows += [f'<div class="r bad"><b class="d">!</b>{escape(w)}</div>' for w in self.warnings]
        total = time.perf_counter() - self.starts[0]
        return (f'{PROGRESS_CSS}<div class="lsi"><b>LSI Lite &middot; {escape(self.title)}</b> '
                f'<small>{total:.0f} s</small>{"".join(rows)}</div>')


# --- 3D-ANSICHT ---

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


def show_paths(layer_paths, strokes=None, mid=None, max_points=300_000, max_strokes=2000):
    """Drehbare 3D-Ansicht der Bahnen, Zugstriche und Mittelschicht per Klick auf die Legende."""
    import plotly.graph_objects as go
    total = sum(len(P) for paths in layer_paths for P in paths)
    step = max(1, -(-total // max_points))
    xyz, color = [], []
    for k, paths in enumerate(layer_paths):
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
        s = strokes[::max(1, len(strokes) // max_strokes)]
        s = np.concatenate([s, np.full((len(s), 1, 3), np.nan)], axis=1).reshape(-1, 3)
        fig.add_trace(go.Scatter3d(x=s[:, 0], y=s[:, 1], z=s[:, 2], mode="lines",
                                   name="Zugrichtung (sigma_1)", visible="legendonly",
                                   line=dict(color="black", width=3)))
    if mid is not None:
        fig.add_trace(go.Surface(x=mid[0], y=mid[1], z=mid[2], name="Mittelschicht",
                                 visible="legendonly", showlegend=True, showscale=False,
                                 colorscale=[[0, "magenta"], [1, "magenta"]]))
    fig.update_layout(scene=dict(aspectmode="data", xaxis_title="x", yaxis_title="y",
                                 zaxis_title="z"),
                      margin=dict(l=0, r=0, t=30, b=0), height=600,
                      legend=dict(x=0, y=1),
                      title=f"Bahnen aller {len(layer_paths)} Schichten"
                            + (f" (jeder {step}. Punkt)" if step > 1 else ""))
    return fig
