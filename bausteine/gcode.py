"""G-Code schreiben: Bahnen mit Extrusionsmenge, Vorschub und Leerfahrten."""

import math

import numpy as np

from bausteine.config import FILAMENT, MAX_SPEED, MIN_SPEED, RETRACT_SPEED, TRAVEL_SPEED, Z_HOP


def bead_area(h, w):
    """Querschnitt einer Bahn: Rechteck mit runden Flanken."""
    h = np.minimum(h, w)
    return (w - h) * h + math.pi * h * h / 4


class GcodeWriter:
    """Schreibt Bahnen als G-Code; Leerfahrten heben ueber die aktuelle Schicht."""

    def __init__(self, w, h_nom, retract):
        self.lines, self.pos, self.w, self.retract = [], None, w, retract
        self.flow = bead_area(h_nom, w)
        self.filament = math.pi * FILAMENT ** 2 / 4
        self.e_total, self.seconds = 0.0, 0.0

    def travel(self, target, surface):
        """Leerfahrt mit Rueckzug, ueber die hoechste Stelle der Schicht auf dem Weg."""
        if self.pos is None:
            self.lines += [f"G0 X{target[0]:.3f} Y{target[1]:.3f} F{TRAVEL_SPEED * 60:.0f}",
                           f"G0 Z{target[2]:.3f}"]
        else:
            t = np.linspace(0, 1, 12)[:, None]
            way = self.pos[:2] + t * (target[:2] - self.pos[:2])
            z_safe = max(surface(way).max(), self.pos[2], target[2]) + Z_HOP
            way_len = 2 * z_safe - self.pos[2] - target[2] + np.linalg.norm(target[:2] - self.pos[:2])
            self.seconds += way_len / TRAVEL_SPEED + 2 * self.retract / RETRACT_SPEED
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
        self.seconds += float(np.sum(len_3d / feed))
        self.pos = P[-1]
