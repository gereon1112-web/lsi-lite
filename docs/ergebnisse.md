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
