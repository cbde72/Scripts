# INI-Export V04

`ini_export.py` erzeugt aus den vollständigen `Phase`-Objekten zwei Dateien im
Format von `ConfigGUI_V0_2` und validiert sie anschließend mit
`load_profiles()` und `load_load_cycle()`.

Der Export reduziert Temperaturpunkte nur bei exakt gleicher Steigung. Feuchte-
und Operationswechsel bleiben erhalten. Die Operationszuordnung steht zentral
in `DEFAULT_OPERATION_MAP`; unbekannte Modi werden abgewiesen. Zeitpunkte werden
nicht gerundet: Das INI-/PLC-Modell akzeptiert ausschließlich ganze Sekunden.

Die GUI ordnet die acht ENV-Tests stabil den Slots 1 bis 8 zu und lässt die
restlichen Slots aus der Vorlage unverändert. Vorhandene Exportdateien werden
nur nach Bestätigung überschrieben.

## Exportgrenzen

Ein vollständiger Test ist nur dann exportierbar, wenn seine exakten
Phasenwechsel, Feuchtewerte, binären Operationszustände und Actuator-Ereignisse
mit höchstens 32 Punkten je Kurve und ganzzahligen Sekunden darstellbar sind.
`n.def.`-Feuchte ist im bestehenden INI-Format nicht darstellbar und führt zu
einem eindeutigen Fehler. Ebenso werden nicht darstellbare Sprungflanken oder
mehr als 32 notwendige Liftpunkte nicht stillschweigend vereinfacht. Für diese
Fälle müsste das INI-/SPS-Datenmodell um undefinierte Feuchte, feinere Zeitbasis,
Segmentierung oder eine explizite Ablaufsteuerung erweitert werden.
