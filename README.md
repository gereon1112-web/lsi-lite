# LSI Lite

Lastoptimiert slicen aus einem FEM-Ergebnis: Aus einer `.vtu`-Datei mit Spannungsfeld
entsteht G-Code für einen 3-Achs-Drucker, dessen Schichten der Zugspannung folgen.
Eine einzige Python-Datei (`lsi_lite.py`), gedacht für Google Colab.

LSI Lite ist die verkleinerte Fassung des *Load-Optimized Surface Interpolator* (LSI)
aus der Diplomarbeit von Gereon Zündorf. Das Grundprinzip ist dasselbe, der Umfang
ein Zwanzigstel (siehe [Was vereinfacht ist](#was-vereinfacht-ist)).

## Benutzung in Google Colab

Du brauchst nur ein Google-Konto und deine `.vtu`-Datei.

1. Notebook öffnen:
   <https://colab.research.google.com/github/gereon1112-web/lsi-lite/blob/main/LSI_lite.ipynb>
   (oder in Colab *Datei → Notebook öffnen → GitHub*, `gereon1112-web/lsi-lite` eingeben).
2. **Zelle 1 „Einrichten"** mit ▶ starten. Beim ersten Mal fragt Colab, ob du dem
   Notebook vertraust: *Trotzdem ausführen*. Nach etwa 20 Sekunden steht „Bereit."
3. **Zelle 2 „Datei hochladen"** starten, *Dateien auswählen*, deine `.vtu` wählen.
4. **Zelle 3 „Einstellungen und Rechnen"**: das Formular rechts ausfüllen
   (Tabelle unten), dann ▶. Je nach Bauteil dauert das 5 Sekunden bis 2 Minuten.
   Ausgegeben werden ein Protokoll und ein Vorschaubild:
   links ein Schnitt durch die Schichten (rot die lastoptimierte Mittelschicht),
   rechts, wie weit die Mittelschicht nach oben oder unten ausweicht.
5. **Zelle 4 „Ansehen"** zeigt die Bahnen in 3D, mit der Maus drehbar, Farbe = Schicht.
   Mit „bis_schicht" (z. B. auf die Hälfte) schaust du ins Innere.
6. **Zelle 5 „Herunterladen"** speichert den G-Code (`<name>_lite.gcode`).

Ändern sich nur Einstellungen, genügt es, ab Zelle 3 neu zu starten.

**Was das Protokoll sagt:**

| Zeile | Bedeutung |
| --- | --- |
| Zug in der Schicht 21 % → 28 % | Anteil der Zugspannung, der in der Schicht liegt statt quer durch die Lagenfuge zu ziehen – vor und nach der Optimierung |
| Neigung max | steilste Stelle der Mittelschicht; höchstens die eingestellte Grenze |
| Dicke 0.19 .. 0.30 mm | Schichtdicke senkrecht zur Schicht (5. bis 95. Perzentil) |
| ACHTUNG: Schichtdicke … | die Schichten verlassen das Fenster – Fenster weiten oder Neigung senken |
| ACHTUNG: Überhang … | Teile der Schichten hängen in der Luft – andere Baurichtung wählen |

## Einstellungen

| Feld | Bedeutung | Vorgabe |
| --- | --- | --- |
| duese | Düsendurchmesser in mm | 0.4 |
| schicht_min, schicht_max | dünnste und dickste Schicht, die der Drucker sauber legt | 0.1, 0.35 |
| neigung_max | wie steil eine Schicht stehen darf (Grad); kleiner als der Freiwinkel von Düse und Heizblock | 20 |
| fuellung | `konzentrisch` (Ringe parallel zum Rand) oder `zigzag` (Linien, je Schicht um 90° gedreht) | konzentrisch |
| fuelldichte | 100 = massiv, 0 = nur Wände | 100 |
| waende | Anzahl Wandbahnen | 1 |
| drucker | legt die Bettgröße fest | 220 x 220 |
| material | Temperaturen, Lüfter, Rückzug | PLA |
| baurichtung | welche Achse des FEM-Modells beim Druck nach oben zeigt | +z |

Die Bahnbreite ist Düse + größte Schichthöhe (wie im Original). Weitere feste Werte
(Geschwindigkeiten, Rückzug, Start-G-Code) stehen oben in `lsi_lite.py`.

**Die Eingabedatei:** ein Tetraedernetz (C3D4 oder C3D10) mit Spannungstensor je Knoten,
z. B. der VTU-Export eines CalculiX-Ergebnisses aus FreeCAD (Felder
„Stress xx component" usw.) oder ein Feld `stress` mit 6 oder 9 Komponenten.
Die Unterseite des Bauteils muss in Baurichtung eben auf dem Bett liegen.
Maße in mm; Modelle in Metern werden erkannt und umgerechnet.

## Benutzung auf dem eigenen Rechner

Voraussetzung: Python 3.10 oder neuer.

| Schritt | Linux | Windows |
| --- | --- | --- |
| Umgebung anlegen | `python3 -m venv .venv` | `py -m venv .venv` |
| Pakete installieren | `.venv/bin/pip install -r requirements.txt` | `.venv\Scripts\pip install -r requirements.txt` |
| `.vtu` in den Ordner `eingabe/` legen, dann starten | `.venv/bin/python lsi_lite.py` | `.venv\Scripts\python lsi_lite.py` |
| oder mit Pfad | `.venv/bin/python lsi_lite.py teil.vtu` | `.venv\Scripts\python lsi_lite.py teil.vtu` |

Die Einstellungen stehen dann oben in `lsi_lite.py` unter `SETTINGS`. G-Code und
Vorschaubild landen neben der `.vtu`. Unter Windows ist das bisher nicht getestet.

## Wie es rechnet

1. **Quader und Raster.** Um das Bauteil liegt ein Quader, doppelt so hoch wie das Bauteil,
   darüber ein Raster in der Draufsicht (größte Ausdehnung / 60).
2. **Mittelschicht.** Eine Fläche auf halber Höhe wird so verbogen, dass die größte
   Hauptspannung in ihr liegt, statt quer durch die Lagenfuge zu ziehen. Das ist eine
   Ausgleichsrechnung mit genau zwei Grenzen: Neigung und Auslenkung (aus dem
   Schichthöhenfenster). Gewichtet wird nur Zug.
3. **Schichten dazwischen.** Ein Feld u ist 0 auf dem Bett, 1 auf der Mittelschicht
   (bzw. Mittelschicht und Deckel); dazwischen ist jeder Punkt das Mittel seiner Nachbarn
   (Laplace-Gleichung, lineare finite Elemente). Die Schichten sind die Flächen gleichen
   u-Werts: Sie können sich nicht schneiden, und Knicke der Mittelschicht runden sich
   zum Bett und zum Deckel hin ab.
4. **Abschneiden.** Jede Schicht wird am Bauteil beschnitten.
5. **Bahnen.** Wände und Füllung je Schicht, auf die Schichtfläche gehoben.
6. **G-Code.** Die Menge folgt der örtlichen Schichtdicke; der Vorschub wird so
   nachgeführt, dass der Volumenstrom gleich bleibt. Leerfahrten heben über die
   höchste Stelle der Schicht.

## Was vereinfacht ist

| Teil | Original (LSI) | Lite |
| --- | --- | --- |
| Feld u | Tetraedernetz aus tetgen | Säulennetz über dem Raster; gleiche Gleichung, Elemente und Randwerte |
| Vorgabeflächen | Bauteilunter- und -oberseite wählbar | Unterseite = Bett (eben), Oberseite nicht vorgegeben |
| Bahnabstand | auf der Fläche (geodätisch) | in der Draufsicht; auf einer um 20° geneigten Stelle liegen Bahnen 6 % weiter auseinander, die Menge stimmt trotzdem, die Raupe wird dort etwas breiter und flacher |
| Füllarten | konzentrisch, zigzag, lastgeführt (explizit, implizit) | konzentrisch, zigzag |
| Drucker | 3-Achs und 6-Achs-Roboter (RAPID), Draht | nur 3-Achs |
| Prüfungen | Druckbarkeitskriterien K1 bis K7 | Schichthöhenfenster, Überhang, Bettgröße |

**Vergleich mit dem Original** (gleiche Bauteile, gleiche Grenzen, 2026-11-08):

| | Zug in der Schicht vorher → nachher | Neigung max | Neigung der Schicht bei 60 % / 70 % der Quaderhöhe |
| --- | --- | --- | --- |
| Tragwerk, Original | 79 % → 88 % | 19.7° | 10.5° / 7.5° |
| Tragwerk, Lite | 82 % → 90 % | 20.0° | 10.1° / 5.9° |
| Biegebalken, Original | 21 % → 29 % | 9.6° | 5.5° / 4.0° |
| Biegebalken, Lite | 21 % → 28 % | 7.8° | 4.5° / 3.2° |

Die Schichten klingen nach oben so ab wie im Feld des Originals; eine gleichmäßige
Überblendung (wie *Tween* in Pufferfish) hätte beim Tragwerk bei 70 % noch etwa 11°.

## Grenzen

- Keine Stützen. Überhänge werden gemeldet, nicht behoben.
- Keine Kollisionsprüfung für Düse und Heizblock über die Neigungsgrenze hinaus.
- Bisher nur am Bildschirm geprüft (G-Code-Viewer des LSI), noch nicht gedruckt.
