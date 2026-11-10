# Verfahren

Wie LSI Lite aus dem FEM-Ergebnis G-Code macht und was gegenüber dem Original-LSI
vereinfacht ist. Messwerte stehen in [ergebnisse.md](ergebnisse.md), Gründe in
[entscheidungen.md](entscheidungen.md).

## Wie es rechnet

1. **Quader und Raster.** Um das Bauteil liegt ein Quader, doppelt so hoch wie das Bauteil,
   je eine halbe Bauteilhöhe darüber und darunter (wie `PART_BOUNDS_AS_LAYERS = None` im
   LSI: keine Bauteilseite gibt die Schichten vor). Darüber ein Raster in der Draufsicht
   (größte Ausdehnung / 60).
2. **Mittelschicht** (`warp_mid`). Eine Fläche auf halber Höhe wird so verbogen, dass die
   größte Hauptspannung in ihr liegt, statt quer durch die Lagenfuge zu ziehen. Das ist
   eine Ausgleichsrechnung mit genau zwei Grenzen: Neigung und Auslenkung (aus dem
   Schichthöhenfenster). Gewichtet wird nur Zug.
   Das geschieht in 5 Stufen (`MID_STAGES`): Die Zugrichtung wird jedes Mal dort neu
   abgelesen, wo die Fläche inzwischen liegt. Jede Stufe übernimmt die Hälfte der neuen
   Verformung (`MID_DAMPING`), damit die Fläche nicht hin- und herspringt; das Ergebnis
   ist die Lösung der letzten Stufe. Wie `MID_RESAMPLE_ROUNDS` im LSI.
3. **Schichten dazwischen** (`laplace_layers`). Ein Feld u ist 0 auf dem Quaderboden, 1 auf der
   Mittelschicht (bzw. Mittelschicht und Deckel); dazwischen ist jeder Punkt das Mittel
   seiner Nachbarn (Laplace-Gleichung, lineare finite Elemente). Die Schichten sind die
   Flächen gleichen u-Werts: Sie können sich nicht schneiden, und Knicke der
   Mittelschicht runden sich zu Boden und Deckel hin ab.
4. **Abschneiden und Fenster erzwingen.** Jede Schicht wird am Bauteil beschnitten. Jeder
   Punkt liegt dabei mindestens die kleinste Schichthöhe (senkrecht zur Schicht) und
   höchstens die größte über dem, was wirklich darunter liegt: dem Bett oder der zuletzt
   gedruckten Schicht. Wo eine gekrümmte Schicht das Bett schräg schneidet, wäre der
   Abstand sonst beliebig klein; dort wird der Punkt angehoben, und die nächste Schicht
   liegt entsprechend weniger hoch darüber. Eine Warnung zur Schichtdicke gibt es deshalb
   nicht.
5. **Bahnen.** Eine Wand und die Füllung je Schicht, auf die Schichtfläche gehoben.
6. **G-Code.** Die Menge folgt der örtlichen Schichtdicke; der Vorschub wird so
   nachgeführt, dass der Volumenstrom gleich bleibt. Leerfahrten heben über die höchste
   Stelle der Schicht.

**Schichthöhe aus der Düse.** Faustregel: mindestens 25 %, höchstens 75 % des
Düsendurchmessers (`LAYER_RATIO`), im Mittel 50 %. Darunter fließt das Material nicht
gleichmäßig, darüber drückt die Düse den Strang nicht mehr an. Die Bahnbreite ist Düse
plus größte Schichthöhe: An der dicksten Stelle liegt der Strang frei, sonst wird er
angedrückt (wie im LSI). Bei 0.4 mm: Schicht 0.10 bis 0.30 mm, Bahn 0.70 mm.

## Was vereinfacht ist

| Teil | Original (LSI) | Lite |
| --- | --- | --- |
| Feld u | Tetraedernetz aus tetgen | Säulennetz über dem Raster; gleiche Gleichung, Elemente und Randwerte |
| Vorgabeflächen | Bauteilunter- und -oberseite wählbar (`PART_BOUNDS_AS_LAYERS`) | keine (wie `None`) |
| Schichthöhe | Fenster frei einstellbar | aus der Düse (25 bis 75 %) |
| Bahnabstand | auf der Fläche (geodätisch) | in der Draufsicht; auf einer um 20° geneigten Stelle liegen Bahnen 6 % weiter auseinander, die Menge stimmt trotzdem, die Raupe wird dort etwas breiter und flacher |
| Füllarten | konzentrisch, zigzag, lastgeführt (explizit, implizit) | konzentrisch, zigzag, explizit |
| Drucker | 3-Achs und 6-Achs-Roboter (RAPID), Draht | nur 3-Achs |
| Wände | Anzahl einstellbar | eine |
| Prüfungen | Druckbarkeitskriterien K1 bis K7 | Schichthöhenfenster (erzwungen), Bettgröße; kein Überhang |

**Neigungsgrenze.** Die Herleitung (kleinerer Winkel aus Düsenkegel und Schlitten über
der Bauteillänge, nach CurviSlicer) steht im Anhang der Diplomarbeit. Die Grenze durch
den Schlitten ist dort vorsichtig gerechnet: Sie nimmt eine Schicht an, die über das
ganze Bauteil gleichmäßig ansteigt; gewellte Schichten steigen weniger hoch.
