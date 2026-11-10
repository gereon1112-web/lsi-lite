# Entscheidungen

Warum LSI Lite so gebaut ist, je Entscheidung mit verworfenen Wegen. Messwerte stehen in
[ergebnisse.md](ergebnisse.md).

## Schichten zwischen den Vorgabeflächen (2026-11-08)

- **Problem:** Netzbau mit tetgen und das Feld des LSI sind rund 1200 Zeilen; Lite soll
  klein bleiben, aber nah am Original rechnen.
- **Verworfen:** Überblendung je Rasterspalte (wie Tween in Pufferfish), die die
  Diplomarbeit ausdrücklich ablehnt; Zerlegung in Wellen (neue Näherung).
- **Gewählt:** dieselbe Laplace-Gleichung mit denselben Elementen und Randwerten, nur das
  Netz als Säulen über dem Raster. Die Schichten fallen direkt als Höhenfelder an.

## Unterseite bleibt das Bett (2026-11-10)

- **Frage:** Unterseite freigeben wie `PART_BOUNDS_AS_LAYERS = None` im LSI, damit die
  Mittelschicht nach unten mehr Raum hat.
- **Problem dabei:** Eine gekrümmte Schicht schneidet das ebene Bett schräg. Gedruckt wird
  dort der Abstand zwischen Bett und Schicht, und der schrumpft am Schnittrand bis auf null.
- **Gemessen:** Über alle Schichten kein Gewinn, dazu Überhänge und zu dicke Schichten
  ([ergebnisse.md](ergebnisse.md#freie-unterseite-statt-bett-als-vorgabe-2026-11-10)).
- **Gewählt:** Bett als Vorgabe beibehalten.

## Schichthöhe aus der Düse (2026-11-10)

- **Gewählt:** 25 bis 75 % des Düsendurchmessers statt zwei freier Felder; eine
  Einstellung weniger, und das Fenster passt immer zur Düse.
- **Verworfen:** freies Fenster wie im LSI (erlaubte Werte, die die Düse nicht drucken kann).

## Notebook mit Colab-Formularen (2026-11-10)

- **Gewählt:** Einstellungen als `#@param`-Formulare in den Zellen; die Schrittliste als
  HTML, das sich in Colab und VS Code gleich aktualisiert.
- **Verworfen:** eine eigene Oberfläche mit ipywidgets. Sie lief in beiden Umgebungen
  gleich, wirkte in Colab aber fremd, und VS Code zeigte sie mit einer veralteten
  Jupyter-Erweiterung nicht an.

## Weitergabe (2026-11-08)

- **Gewählt:** eigenes öffentliches Repo; das Colab-Notebook lädt `lsi_lite.py` über die
  raw-URL.
- **Verworfen:** Gist (keine Versionen), Code nur im Notebook (schwer zu pflegen), PyPI
  (zu viel Aufwand).
