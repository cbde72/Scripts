"""Lossless export of ENV phase timelines to the ConfigGUI INI format."""
from __future__ import annotations

import configparser
import math
from pathlib import Path

from ConfigGUI_V0_2.cycle_transfer_ads import load_load_cycle, load_profiles
from env_cycle_generator import load_percent_at

MAX_SECONDS = 2_147_483
MAX_POINTS = 32
# Deliberately explicit: the PLC format stores a binary operation signal.
# Change this table only after the PLC meaning of a mode has been agreed.
DEFAULT_OPERATION_MAP = {
    "1.1": 0, "1.2": 0,
    "2.1": 0, "2.2": 0, "2.3": 0, "2.4": 0,
    "3.1": 1, "3.2": 1, "3.3": 1, "3.4": 1,
}


def _second(value, label):
    rounded = round(value)
    if not math.isclose(value, rounded, abs_tol=1e-9):
        raise ValueError(f"{label}: {value:g} s ist nicht als ganze Sekunde darstellbar")
    if not 0 <= rounded <= MAX_SECONDS:
        raise ValueError(f"{label}: ausserhalb 0..{MAX_SECONDS} s")
    return int(rounded)


def _append(points, time_s, value):
    point = (_second(time_s, "Zeitpunkt"), float(value))
    if points and points[-1][0] == point[0]:
        if not math.isclose(points[-1][1], point[1], abs_tol=1e-12):
            raise ValueError(f"Mehrere unterschiedliche Werte bei t={point[0]} s")
        return
    if points and point[0] <= points[-1][0]:
        raise ValueError("Zeitpunkte muessen streng steigen")
    points.append(point)


def _reduce(points, linear=False):
    result = []
    for point in points:
        result.append(point)
        while linear and len(result) >= 3:
            (ta, va), (tb, vb), (tc, vc) = result[-3:]
            left = (vb-va)/(tb-ta)
            right = (vc-vb)/(tc-tb)
            if math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12):
                result.pop(-2)
            else:
                break
    if len(result) > MAX_POINTS:
        raise ValueError(f"Mehr als {MAX_POINTS} Stuetzpunkte erforderlich")
    return result


def _curve_points(phases, field, operation_map):
    points = []
    elapsed = 0.0
    for phase in phases:
        if field == "temperature":
            _append(points, elapsed, phase.temperature_start_c)
            _append(points, elapsed + phase.duration_s, phase.temperature_end_c)
        elif field == "humidity":
            if phase.humidity_rh is None:
                label = phase.undefined_humidity_label or "n.def."
                raise ValueError(f"Feuchte {label} ist im INI-Format nicht darstellbar")
            _append(points, elapsed, phase.humidity_rh)
        else:
            if phase.mode not in operation_map:
                raise ValueError(f"Keine ausdrueckliche Operation-Zuordnung fuer Mode {phase.mode}")
            _append(points, elapsed, operation_map[phase.mode])
        elapsed += phase.duration_s
    if field == "humidity":
        _append(points, elapsed, phases[-1].humidity_rh)
    elif field == "operation":
        _append(points, elapsed, operation_map[phases[-1].mode])
    return _reduce(points, linear=field == "temperature")


def _ini_points(section, prefix, label, points):
    section[prefix + label + "Points"] = str(len(points))
    for index, (time_s, value) in enumerate(points, 1):
        section[prefix + f"{label}{index:02}_Time"] = str(time_s)
        section[prefix + f"{label}{index:02}_Set"] = format(value, ".12g")


def export_ini(phases, timeline, parameters, test_id, output_dir, slot=1,
               template_dir=None, operation_map=None, overwrite=False):
    """Write both INIs and return a compact report dictionary.

    Existing template slots are retained; only the selected slot is replaced.
    """
    if not phases:
        raise ValueError("Keine Phasen zum Export vorhanden")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    template_dir = Path(template_dir or Path(__file__).parent / "ConfigGUI_V0_2" / "config")
    test_path, load_path = output_dir / "TestCycleConfig.ini", output_dir / "LoadCycleConfig.ini"
    if not overwrite and (test_path.exists() or load_path.exists()):
        raise FileExistsError("Exportdateien existieren bereits; Ueberschreiben bestaetigen")
    operation_map = operation_map or DEFAULT_OPERATION_MAP
    duration = _second(timeline.duration_s, "Gesamtdauer")
    temp = _curve_points(phases, "temperature", operation_map)
    humidity = _curve_points(phases, "humidity", operation_map)
    operation = _curve_points(phases, "operation", operation_map)

    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read(template_dir / "TestCycleConfig.ini", encoding="utf-8-sig")
    if set(parser.sections()) != {"TestCycleConfig"} | {f"Config{i}" for i in range(1, 21)}:
        raise ValueError("TestCycleConfig-Vorlage muss Config1..Config20 enthalten")
    section = parser[f"Config{slot}"]; prefix = f"Config{slot}_"
    section[prefix+"Enabled"] = "1"; section[prefix+"Name"] = test_id
    section[prefix+"Duration"] = str(duration)
    _ini_points(section, prefix, "Temperature", temp)
    _ini_points(section, prefix, "Humidity", humidity)
    _ini_points(section, prefix, "Operation", operation)
    parser.write(test_path, encoding="utf-8")

    load_points = []
    for t in timeline.actuator_events:
        _append(load_points, t, load_percent_at(timeline.phases, timeline.starts, t, parameters, timeline.load_schedule))
    if not load_points:
        load_points = [(0, 0.0), (duration, 0.0)]
    load_points = _reduce(load_points)
    lp = configparser.ConfigParser(interpolation=None, strict=True); lp.optionxform = str
    lp["LoadCycleConfig"] = {"SchemaVersion": "1"}
    lp["LoadCycle"] = {"LoadCycle_Name": test_id, "LoadCycle_Duration": str(duration)}
    _ini_points(lp["LoadCycle"], "LoadCycle_", "Lift", load_points)
    lp.write(load_path, encoding="utf-8")
    load_profiles(test_path); load_load_cycle(load_path)
    return {"test_id": test_id, "duration_s": duration,
            "points": {"temperature": len(temp), "humidity": len(humidity),
                       "operation": len(operation), "lift": len(load_points)},
            "slot": slot, "segments": 1, "status": "kompatibel", "assumptions": []}
