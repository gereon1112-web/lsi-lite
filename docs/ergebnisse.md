# Ergebnisse

Messungen an den beiden Beispielen in `beispiele/`. Das Verfahren steht in
[verfahren.md](verfahren.md). „Zug in der Schicht“ ist der Anteil der Zugspannung, der in
der Schicht liegt statt quer durch die Lagenfuge zu ziehen, gewichtet mit dem Zug.

## Vergleich mit dem Original (2026-11-08)

Gleiche Bauteile und Grenzen, Schichthöhe 0.1 bis 0.35 mm, Mittelschicht einstufig.

| | Zug in der Mittelschicht vorher → nachher | Neigung max | Neigung der Schicht bei 60 % / 70 % der Quaderhöhe |
| --- | --- | --- | --- |
| Tragwerk, Original | 79 % → 88 % | 19.7° | 10.5° / 7.5° |
| Tragwerk, Lite | 82 % → 90 % | 20.0° | 10.1° / 5.9° |
| Biegebalken, Original | 21 % → 29 % | 9.6° | 5.5° / 4.0° |
| Biegebalken, Lite | 21 % → 28 % | 7.8° | 4.5° / 3.2° |

Die Schichten klingen nach oben so ab wie im Feld des Originals; eine gleichmäßige
Überblendung (wie *Tween* in Pufferfish) hätte beim Tragwerk bei 70 % noch etwa 11°.

## Mittelschicht in 5 Stufen (2026-11-10)

Düse 0.4 (Schicht 0.1 bis 0.3 mm), Neigung 20°.

| | Zug in der Mittelschicht, einstufig | mit 5 Stufen | Rechenzeit |
| --- | --- | --- | --- |
| Tragwerk | 82 % → 90 % | 82 % → 96 % | 38 s (vorher 29 s) |
| Biegebalken | 21 % → 39 % | 21 % → 78 % | 3 s |

Ein Teil des Gewinns kommt daher, dass die Mittelschicht in Gegenden mit mehr Zug wandert,
die dann stärker zählen. Beim Tragwerk ist die Fläche nach 5 Stufen nicht ganz zur Ruhe
(letzte Änderung 1.8 mm), und die Schichtdicke reicht bis 0.33 mm (das Protokoll warnt).

## Freie Unterseite statt Bett als Vorgabe (2026-11-10)

Wie `PART_BOUNDS_AS_LAYERS = None` im LSI: Die Schichten beziehen sich auf den Quaderboden
eine halbe Bauteilhöhe unter dem Bett; am Bett wird das Schichthöhenfenster je Punkt
erzwungen ([verfahren.md](verfahren.md#wie-es-rechnet), Schritt 4). Gemessen wurde
zusätzlich der Zug über **alle** Schichten im Bauteil, nicht nur in der Mittelschicht.

| | Mittelschicht, Bett | Mittelschicht, frei | alle Schichten, Bett | alle Schichten, frei |
| --- | --- | --- | --- | --- |
| Biegebalken | 78 % | 83 % | 83.7 % | 82.9 % |
| Tragwerk | 96 % | 96 % | 81.5 % | 82.3 % |

| mit freier Unterseite | Schichten | Dicke senkrecht zur Schicht (5. bis 95. Perzentil) | tiefster druckender Punkt im G-Code | Rechenzeit |
| --- | --- | --- | --- | --- |
| Biegebalken | 87 | 0.10 .. 0.30 mm | 0.10 mm | 3 s |
| Tragwerk | 64 | 0.10 .. 0.30 mm | 0.10 mm | 38 s |

Die Mittelschicht darf weiter ausweichen (Biegebalken −5.2 statt −3.5 mm); über das ganze
Bauteil ändert sich wenig. Die Schichtdicke bleibt jetzt im Fenster, vorher reichte sie
beim Tragwerk bis 0.33 mm.

## Mittelschicht nachgeglättet (2026-11-19)

Knick = Änderung der Steigung von einem Rasterknoten zum nächsten, als Höhe in mm
(zweite Differenz des Versatzes entlang x); 99. Perzentil und größter Wert.

| | Zug in der Mittelschicht | Neigung max | Knick 99 % / max |
| --- | --- | --- | --- |
| Tragwerk, Düse 1, 25°, vorher | 82 % → 96 % | 25.0° | 0.79 / 1.32 mm |
| Tragwerk, Düse 1, 25°, geglättet | 82 % → 98 % | 16.3° | 0.26 / 0.47 mm |
| Tragwerk, 20°, vorher | 82 % → 96 % | 20.0° | 0.67 / 1.25 mm |
| Tragwerk, 20°, geglättet | 82 % → 98 % | 16.0° | 0.24 / 0.38 mm |
| Biegebalken, 20°, vorher | 21 % → 83 % | 19.8° | 0.38 / 0.51 mm |
| Biegebalken, 20°, geglättet | 21 % → 83 % | 15.4° | 0.15 / 0.17 mm |

Die Düse ändert an der Mittelschicht nichts (gleiche Werte bei 0.4 und 1 mm). Die
Neigungsgrenze wird nach dem Glätten nicht mehr ausgeschöpft; die Fläche ist runder,
nicht flacher in der Ausrichtung.

## Schichtrand am echten Abstand (2026-11-19)

Tragwerk, Neigung 25°, mittlere Hälfte der Schichten. Gemessen ist, wie weit die
Außenwand vom Sollabstand (halbe Bahnbreite zur Hülle) abweicht.

| | Abweichung Median / 95 % | Umrisspunkte aller Schichten | Rechenzeit (Düse 0.4) |
| --- | --- | --- | --- |
| Düse 1, vorher | 0.18 / 0.50 mm | | |
| Düse 1, nachher | 0.02 / 0.61 mm | | |
| Düse 0.4, vorher | 0.08 / 0.15 mm | 36 761 | 40 s, davon 26 s Bahnen legen |
| Düse 0.4, nachher | 0.00 / 0.23 mm | 11 864 | 13 s, davon 1 s Bahnen legen |

Entlang der Wände liegt die Bahn jetzt auf dem Sollabstand. Das 95. Perzentil steigt, weil
an Ecken und Armspitzen der Abstand zur Hülle vom Sollwert abweicht (die Wand rundet die
Ecke ab); die alte Treppe hatte dort zufällig ähnliche Werte. Die Beschleunigung kommt aus
dem Bahnenlegen: Das wiederholte Einrücken der Umrisse für die konzentrische Füllung ist
bei treppigen Umrissen mit dreimal so vielen Punkten viel teurer.

