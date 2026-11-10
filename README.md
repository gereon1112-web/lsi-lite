# LSI Lite

[![In Colab öffnen](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gereon1112-web/lsi-lite/blob/main/LSI_lite.ipynb)

Macht aus einem FEM-Ergebnis (`.vtu` mit Spannungsfeld) G-Code für einen 3-Achs-Drucker,
dessen Schichten der Zugspannung folgen. Verkleinerte Fassung des LSI aus der
Diplomarbeit von Gereon Zündorf. Prototyp, noch nicht gedruckt.

## Starten

**Im Browser, ohne Installation:**
<https://colab.research.google.com/github/gereon1112-web/lsi-lite/blob/main/LSI_lite.ipynb>
(Google-Konto nötig). Die Einstellungen stehen dort als Formular neben den Zellen.

**Lokal in VS Code:**

1. `git clone https://github.com/gereon1112-web/lsi-lite.git`
2. In VS Code die Erweiterung **Jupyter** installieren, den Ordner öffnen, `LSI_lite.ipynb` anklicken.
3. Einmalig: *Kernel auswählen → Python-Umgebungen → Python-Umgebung erstellen → Venv*,
   Haken bei `requirements.txt`. (Vergessen? Zelle 1 installiert die Pakete selbst.)
4. Einstellungen in Zelle 2 und 3 direkt im Code ändern (`duese = 0.6`); VS Code zeigt
   die Colab-Formulare nicht an.

Die Umgebung `.venv` (etwa 1 GB) bleibt im Ordner. Löschen: VS Code schließen, dann
`rm -rf .venv` (Linux) bzw. `rmdir /s /q .venv` (Windows).

**Kommandozeile:** `.venv/bin/python lsi_lite.py teil.vtu` (Windows:
`.venv\Scripts\python lsi_lite.py teil.vtu`). Ohne Pfad nimmt es die `.vtu` aus `eingabe/`;
Einstellungen oben in `lsi_lite.py` unter `SETTINGS`.

Python 3.12 oder neuer. Unter Windows nicht getestet.

## Ablauf im Notebook

| Zelle | was passiert |
| --- | --- |
| 1 Einrichten | Pakete und Programm laden |
| 2 Eingabe | Beispiel (Tragwerk, Biegebalken) oder eigene `.vtu`: in Colab hochladen, lokal in `eingabe/` legen |
| 3 Einstellungen und Rechnen | Werte setzen, ▶; eine Schrittliste zeigt Fortschritt und Ergebnisse |
| 4 Ansehen | alle Bahnen in 3D; schwarze Striche = Zugrichtung |
| 5 Herunterladen | G-Code `<name>_lite.gcode` (lokal: Pfad, neben der `.vtu`) |

Für neue Einstellungen genügt es, ab Zelle 3 neu zu starten.

## Einstellungen

| Feld | Bedeutung | Vorgabe |
| --- | --- | --- |
| duese | Düsendurchmesser in mm; Schichthöhe = 25 bis 75 % davon, Bahnbreite = Düse + größte Schichthöhe | 0.4 |
| neigung_max | wie steil eine Schicht stehen darf, in Grad (siehe unten) | 20 |
| fuellung | `konzentrisch`, `zigzag` oder `explizit` (entlang der Zugrichtung, mit Lücken) | konzentrisch |
| fuelldichte | 100 = massiv, 0 = nur die Wand (eine Bahn am Rand) | 100 |
| drucker | Bettgröße | 220 x 220 |
| material | Temperaturen, Lüfter, Rückzug | PLA |
| baurichtung | welche Achse des FEM-Modells nach oben zeigt; `auto` = bei Beispielen deren Richtung, sonst +z | auto |

### Warum die Neigung begrenzt ist

Die Düse eines 3-Achs-Druckers steht immer senkrecht. Steigt eine Schicht steiler an als
die Flanke von Düse und Heizblock, fährt der Heizblock in das, was schon gedruckt ist.

<p align="center"><img src="bilder/neigungsgrenze.svg" alt="Links eine flache Schicht, die Düse bleibt frei; rechts eine steile Schicht, der Heizblock stößt an" width="720"></p>

`neigung_max` also flacher wählen als diese Flanke am eigenen Druckkopf, bei großen
Bauteilen wegen des Schlittens darüber noch etwas kleiner. Üblich sind 15 bis 25°.

## Eingabedatei

Tetraedernetz (C3D4 oder C3D10) mit Spannungstensor je Knoten, z. B. der VTU-Export aus
FreeCAD/CalculiX (Felder „Stress xx component“ usw.) oder ein Feld `stress` mit 6 oder 9
Komponenten. Maße in mm (Meter werden erkannt). Die Unterseite muss in Baurichtung eben sein.

## Grenzen

- Keine Stützen und keine Überhangprüfung: `baurichtung` so wählen, dass nichts in der Luft hängt.
- Keine Kollisionsprüfung über die Neigungsgrenze hinaus.
- Noch nicht gedruckt; geprüft am Bildschirm und mit einem lokalen Jupyter-Kernel,
  in Colab und VS Code selbst noch nicht angesehen.

## Dokumentation

Wie es rechnet, was gegenüber dem Original vereinfacht ist und was gemessen wurde:
[docs/](docs/README.md).
