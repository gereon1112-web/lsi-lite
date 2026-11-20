"""Feste Werte von LSI Lite; was der Nutzer waehlt, steht im Formular des Notebooks."""

START_GCODE = """\
G21                     ; mm
G90                     ; absolute Koordinaten
M83                     ; Extruder relativ
M104 S{nozzle_temp}
M140 S{bed_temp}
G28                     ; Referenzfahrt
M190 S{bed_temp}
M109 S{nozzle_temp}
M107                    ; Luefter aus
G92 E0
G1 Z2.0 F3000           ; Reinigungslinie am linken Bettrand
G1 X5 Y20 Z0.3 F5000
G1 X5 Y{purge_end} Z0.3 F1500 E15
G1 X5.4 Y{purge_end} Z0.3 F5000
G1 X5.4 Y20 Z0.3 F1500 E15
G92 E0
G1 Z2.0 F3000
"""

END_GCODE = """\
M107
M104 S0
M140 S0
G91
G1 Z10 F600
G90
G28 X
M84
"""

# Druckbett (x, y) in mm.
PRINTERS = {
    "220 x 220 (Ender-3 u. a.)": (220.0, 220.0),
    "250 x 210 (Prusa MK3/MK4)": (250.0, 210.0),
    "256 x 256 (Bambu Lab X1/P1)": (256.0, 256.0),
    "350 x 350 (Voron 2.4 u. a.)": (350.0, 350.0),
}

# Duese, Bett in Grad C, Luefter in %, Faktor auf den Rueckzug.
MATERIALS = {
    "PLA":  (215, 60, 100, 1.0),
    "PETG": (240, 80, 40, 1.3),
    "ABS":  (250, 100, 10, 1.0),
}

GRID_DIVISIONS = 60         # Rasterweite = groesste Ausdehnung / 60
LAYER_RATIO = (0.25, 0.75)  # Schichthoehe min, max als Vielfaches der Duese
FREEDOM = 1e-2              # Restglaettung der Mittelschicht
MID_SMOOTHING = 2.0         # Nachglaettung der Mittelschicht, in Rasterzellen-Flaechen
MID_STAGES = 5              # Stufen: Zugrichtung an der verformten Mittelschicht neu abtasten
MID_DAMPING = 0.5           # Anteil, zu dem jede Stufe den neuen Versatz uebernimmt
OUTER_ITERS = 80            # Runden fuer Neigungs- und Amplitudengrenze
TILT_GROWTH = 3.0
IDW_K, IDW_POWER = 8, 2.0   # Abtastung des FEM-Ergebnisses
PERCENTILE = 90.0           # Bezug der Gewichtung (Zug, Anisotropie)
FILAMENT = 1.75
FIRST_LAYER_FLOW = 1.15
PRINT_SPEED, FIRST_LAYER_SPEED, TRAVEL_SPEED = 30.0, 15.0, 120.0
MIN_SPEED, MAX_SPEED = 5.0, 150.0
RETRACT, RETRACT_SPEED = 1.0, 40.0
Z_HOP = 0.6
FAN_OFF_LAYERS = 2
RESAMPLE = 0.5              # Punktabstand der Bahnen in mm

STRESS_FIELDS = ("Stress xx component", "Stress yy component",
                 "Stress zz component", "Stress xy component",
                 "Stress yz component", "Stress xz component")
# Beispiele: Datei und Baurichtung.
EXAMPLES = {
    "Biegebalken": ("beispiele/biegebalken.vtu", "+y"),
    "Tragwerk": ("beispiele/tragwerk.vtu", "-y"),
}
AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0),
        "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}
