"""Transfer INI temperature profiles (slot 1..20) or the separate common load cycle.
Default is offline validation. --status reads ADS; --stage writes a candidate.
"""
import argparse
import configparser
import math
import secrets
import struct
import time
from pathlib import Path

ROOT = "GVL_CycleTransfer"
CONFIG = Path(__file__).resolve().parent / "config"
MAX_SECONDS = 2147483
STATUS = {"BeginAcknowledged": "UDINT", "ValidatedRequest": "UDINT",
          "AcceptedRequest": "UDINT", "CancelAcknowledged": "UDINT",
          "Receiving": "BOOL", "Ready": "BOOL", "Error": "BOOL", "ErrorID": "UDINT"}


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: ganze Zahl {low}..{high} erforderlich")
    return value


def real(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label}: endlicher REAL erforderlich")
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError(f"{label}: ausserhalb REAL-Bereich") from exc
    if not math.isfinite(result) or abs(result) > 3.402823e38:
        raise ValueError(f"{label}: ausserhalb unterstuetztem REAL-Bereich")
    return result


def keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label}: fehlende/unbekannte Felder; erwartet {', '.join(expected)}")


def validate(payload):
    common = ("Schema", "Name", "Duration_s")
    schema = payload.get("Schema") if isinstance(payload, dict) else None
    if schema == "TemperatureCycle-1":
        if payload.get("Enabled") is False:
            integer(payload["Slot"], 1, 20, "Slot")
            return {"Schema": schema, "Slot": payload["Slot"], "Enabled": False,
                    "Name": "", "Duration_s": 0, "WaitForTempEnable": False,
                    "WaitTempTolerance_K": 0.0, "WaitTempStable_s": 0,
                    "Temp": [], "Humidity": [], "Operation": []}
        keys(payload, common + ("Slot", "WaitForTempEnable", "WaitTempTolerance_K",
                               "WaitTempStable_s", "Temp", "Humidity", "Operation", "Enabled"), "Profil")
        integer(payload["Slot"], 1, 20, "Slot")
        if payload["Enabled"] is not True:
            raise ValueError("Enabled muss bool sein")
        if type(payload["WaitForTempEnable"]) is not bool:
            raise ValueError("WaitForTempEnable muss true/false sein")
        payload["WaitTempTolerance_K"] = real(payload["WaitTempTolerance_K"], "Tolerance")
        if payload["WaitTempTolerance_K"] < 0:
            raise ValueError("Tolerance darf nicht negativ sein")
        integer(payload["WaitTempStable_s"], 0, MAX_SECONDS, "WaitTempStable_s")
        curves = ("Temp", "Humidity", "Operation")
    elif schema == "LoadCycle-1":
        keys(payload, common + ("Lift",), "Lastzyklus")
        curves = ("Lift",)
    else:
        raise ValueError("Schema muss TemperatureCycle-1 oder LoadCycle-1 sein")
    name = payload["Name"]
    if (not isinstance(name, str) or not name.strip() or len(name) > 80
            or any(not 32 <= ord(char) <= 126 for char in name)):
        raise ValueError("Name: 1..80 druckbare ASCII-Zeichen erforderlich")
    duration = integer(payload["Duration_s"], 1, MAX_SECONDS, "Duration_s")
    for curve in curves:
        points = payload[curve]
        if not isinstance(points, list) or not 1 <= len(points) <= 32:
            raise ValueError(f"{curve}: 1..32 Stuetzpunkte erforderlich")
        previous = -1
        for index, point in enumerate(points):
            keys(point, ("Time_s", "Value"), f"{curve}[{index+1}]")
            stamp = integer(point["Time_s"], 0, duration, f"{curve}.Time_s")
            if stamp <= previous or (index == 0 and stamp != 0):
                raise ValueError(f"{curve}: erster Zeitpunkt 0; danach streng steigend")
            previous = stamp
            original = point["Value"]
            value = real(original, f"{curve}.Value")
            if curve in ("Humidity", "Lift") and not 0 <= original <= 100:
                raise ValueError(f"{curve}: Werte 0..100 erforderlich")
            if curve == "Operation" and original not in (0, 1):
                raise ValueError("Operation: ausschliesslich 0 oder 1")
            point["Value"] = value
    return payload


def ini_parser(path):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8-sig"))
    if parser.defaults():
        raise ValueError("[DEFAULT] ist nicht erlaubt")
    return parser


def ini_int(section, key):
    value = section[key]
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"{key}: nichtnegative ganze Zahl erforderlich")
    return int(value)


def ini_bool(section, key):
    if section[key] not in ("0", "1"):
        raise ValueError(f"{key}: 0 oder 1 erforderlich")
    return section[key] == "1"


def ini_curve(section, prefix, label, used):
    count_key = prefix + label + "Points"
    count = integer(ini_int(section, count_key), 1, 32, count_key)
    used.add(count_key)
    points = []
    for index in range(1, count+1):
        time_key = prefix + f"{label}{index:02}_Time"
        value_key = prefix + f"{label}{index:02}_Set"
        used.update((time_key, value_key))
        points.append({"Time_s": ini_int(section, time_key), "Value": float(section[value_key])})
    return points


def load_profiles(path):
    parser = ini_parser(path)
    expected_sections = {"TestCycleConfig"} | {f"Config{slot}" for slot in range(1, 21)}
    if set(parser.sections()) != expected_sections:
        raise ValueError("Abschnitte [TestCycleConfig] und [Config1]..[Config20] erforderlich")
    header = parser["TestCycleConfig"]
    keys(dict(header), ("SchemaVersion", "Slots"), "TestCycleConfig")
    if header["SchemaVersion"] != "1" or header["Slots"] != "20":
        raise ValueError("SchemaVersion=1 und Slots=20 erforderlich")
    profiles = []
    for slot in range(1, 21):
        section = parser[f"Config{slot}"]
        prefix = f"Config{slot}_"
        enabled = ini_bool(section, prefix + "Enabled")
        if not enabled and set(section) == {prefix + "Enabled"}:
            profiles.append(validate({"Schema": "TemperatureCycle-1", "Slot": slot, "Enabled": False}))
            continue
        fields = {"Name": "Name", "Duration_s": "Duration", "WaitForTempEnable": "WaitForTemperatureEnable",
                  "WaitTempTolerance_K": "WaitTemperatureTolerance", "WaitTempStable_s": "WaitTemperatureStableTime"}
        used = {prefix + "Enabled"} | {prefix+key for key in fields.values()}
        payload = {"Schema": "TemperatureCycle-1", "Slot": slot, "Enabled": True,
                   "Name": section[prefix+"Name"], "Duration_s": ini_int(section, prefix+"Duration"),
                   "WaitForTempEnable": ini_bool(section, prefix+"WaitForTemperatureEnable"),
                   "WaitTempTolerance_K": float(section[prefix+"WaitTemperatureTolerance"]),
                   "WaitTempStable_s": ini_int(section, prefix+"WaitTemperatureStableTime")}
        for curve, label in (("Temp", "Temperature"), ("Humidity", "Humidity"), ("Operation", "Operation")):
            payload[curve] = ini_curve(section, prefix, label, used)
        keys(dict(section), sorted(used), prefix)
        # Validate complete inactive templates too, but send canonical empty
        # profile to preserve the PLC's explicit-disable protocol.
        payload = validate(payload)
        if not enabled:
            payload = validate({"Schema": "TemperatureCycle-1", "Slot": slot, "Enabled": False})
        profiles.append(payload)
    return profiles


def load_load_cycle(path):
    parser = ini_parser(path)
    if set(parser.sections()) != {"LoadCycleConfig", "LoadCycle"}:
        raise ValueError("Abschnitte [LoadCycleConfig] und [LoadCycle] erforderlich")
    keys(dict(parser["LoadCycleConfig"]), ("SchemaVersion",), "LoadCycleConfig")
    if parser["LoadCycleConfig"]["SchemaVersion"] != "1":
        raise ValueError("SchemaVersion=1 erforderlich")
    section = parser["LoadCycle"]
    used = {"LoadCycle_Name", "LoadCycle_Duration"}
    payload = {"Schema": "LoadCycle-1", "Name": section["LoadCycle_Name"],
               "Duration_s": ini_int(section, "LoadCycle_Duration"),
               "Lift": ini_curve(section, "LoadCycle_", "Lift", used)}
    keys(dict(section), sorted(used), "LoadCycle")
    return validate(payload)


def candidate_values(payload, version):
    profile = payload["Schema"] == "TemperatureCycle-1"
    yield "CandidateKind", 1 if profile else 2, "UINT"
    yield "CandidateSlot", payload["Slot"] if profile else 1, "UINT"
    yield "CandidateVersion", version, "UDINT"
    prefix = "CandidateProfile" if profile else "CandidateLoad"
    for field, datatype in (("Name", "STRING"), ("Duration_s", "UDINT")):
        yield f"{prefix}.{field}", payload[field], datatype
    if profile:
        for field, datatype in (("WaitForTempEnable", "BOOL"), ("WaitTempTolerance_K", "REAL"),
                                ("WaitTempStable_s", "UDINT")):
            yield f"{prefix}.{field}", payload[field], datatype
    for curve, count in (("Temp", "TempPoints"), ("Humidity", "HumidityPoints"),
                         ("Operation", "OperationPoints")) if profile else (("Lift", "LiftPoints"),):
        points = payload[curve]
        yield f"{prefix}.{count}", len(points), "UINT"
        for index in range(1, 33):
            point = points[index-1] if index <= len(points) else {"Time_s": 0, "Value": 0.0}
            yield f"{prefix}.{curve}[{index}].Time_s", point["Time_s"], "UDINT"
            yield f"{prefix}.{curve}[{index}].Value", point["Value"], "REAL"
    yield f"{prefix}.Valid", payload.get("Enabled", True), "BOOL"


class Transport:
    def __init__(self, connection, pyads, root):
        self.connection, self.pyads, self.root = connection, pyads, root

    def datatype(self, datatype):
        # Individual symbols; no assumptions about STRUCT layout/padding.
        return getattr(self.pyads, "PLCTYPE_" + datatype)

    def read(self, name, datatype):
        return self.connection.read_by_name(f"{self.root}.{name}", self.datatype(datatype))

    def write(self, name, value, datatype):
        self.connection.write_by_name(f"{self.root}.{name}", value, self.datatype(datatype))

    def status(self):
        return {name: self.read(name, datatype) for name, datatype in STATUS.items()}


def describe_status(status):
    code = int(status.get('ErrorID', 0))
    meanings = {0xC001: 'Commit ohne passenden Begin', 0xC002: 'Kandidat beim Abschluss instabil',
                0xC003: 'Profil-/Load-Inhalt, Slot oder Version ungültig',
                0xC004: 'Accept ohne passenden bereiten Kandidaten'}
    return (f'Zyklusempfänger: ErrorID=0x{code:04X} ({code}), '
            f'{meanings.get(code, "Fehlercode gegen aktuellen PLC-Empfänger prüfen")}; Status={status}')


def wait_for(transport, predicate, timeout, ignore_error=False):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = transport.status()
        if status["Error"] and not ignore_error:
            raise RuntimeError(describe_status(status))
        if predicate(status):
            return status
        time.sleep(0.1)
    raise TimeoutError("PLC-Quittierung fehlt; --status pruefen, nicht automatisch wiederholen")


def new_request(transport):
    used = {transport.read(name, "UDINT") for name in
            ("BeginRequest", "CommitRequest", "AcceptRequest", "CancelRequest",
             "BeginAcknowledged", "ValidatedRequest", "AcceptedRequest", "CancelAcknowledged")}
    request = secrets.randbelow(0xFFFFFFFF) + 1
    while request in used:
        request = secrets.randbelow(0xFFFFFFFF) + 1
    return request


def version_symbol(payload):
    return (f"ActiveProfileVersion[{payload['Slot']}]" if payload["Schema"] == "TemperatureCycle-1"
            else "ActiveLoadVersion")


def stage(transport, payload, timeout):
    if transport.read("TransferCapacity", "UINT") != 20:
        raise RuntimeError("PLC ist nicht der 20er-Empfaenger; kein Schreibzugriff")
    state = transport.status()
    if state['Error']:
        raise RuntimeError(describe_status(state))
    if state["Receiving"] or state["Ready"] or state["Error"]:
        raise RuntimeError("Transfer offen/Fehler: --status pruefen; bewusster Abbruch mit --cancel")
    version = transport.read(version_symbol(payload), "UDINT") + 1
    if version > 0xFFFFFFFF:
        raise ValueError("Versionsbereich erschoepft")
    request = new_request(transport)
    transport.write("BeginRequest", request, "UDINT")
    wait_for(transport, lambda s: s["BeginAcknowledged"] == request and s["Receiving"], timeout)
    values = list(candidate_values(payload, version))
    for name, value, datatype in values:
        transport.write(name, value, datatype)
    for name, value, datatype in values:
        if transport.read(name, datatype) != value:
            raise RuntimeError(f"Ruecklesefehler {name}; kein Commit")
    state = transport.status()
    if state['Error']:
        raise RuntimeError(describe_status(state))
    if state["Error"] or not state["Receiving"] or state["BeginAcknowledged"] != request:
        raise RuntimeError("Transferzustand veraendert; kein Commit")
    transport.write("CommitRequest", request, "UDINT")
    wait_for(transport, lambda s: s["Ready"] and s["ValidatedRequest"] == request, timeout)
    return request, version


def accept(transport, payload, request, version, timeout):
    state = transport.status()
    if state['Error']:
        raise RuntimeError(describe_status(state))
    if state["Error"] or not state["Ready"] or state["ValidatedRequest"] != request:
        raise RuntimeError(f'Kandidat für Transfer {request} nicht mehr bereit; Status={state}')
    transport.write("AcceptRequest", request, "UDINT")
    wait_for(transport, lambda s: s["AcceptedRequest"] == request, timeout)
    if transport.read(version_symbol(payload), "UDINT") != version:
        raise RuntimeError("Aktive Version stimmt nicht")


def transfer_all(transport, profiles, timeout, confirmed):
    if not confirmed:
        print("Sammelauftrag nicht bestaetigt; nichts geschrieben.")
        return
    completed = []
    for payload in profiles:
        slot = payload["Slot"]
        try:
            request, version = stage(transport, payload, timeout)
            accept(transport, payload, request, version, timeout)
        except (Exception, KeyboardInterrupt):
            print(f"Sammelauftrag gestoppt bei Config{slot}. Bestaetigt: {completed}")
            print("Aktueller Platz kann bei fehlender Quittierung bereits uebernommen sein; --status pruefen.")
            raise
        completed.append(slot)
        print(f"Config{slot}: Version {version} bestaetigt; "
              f"{'aktiviert' if payload['Enabled'] else 'deaktiviert'}")
    print("Alle 20 Plaetze uebernommen. Load-Zyklus bleibt separat.")


def confirm_accept(prompt):
    while True:
        answer = input(prompt + " [j/n]: ").strip().lower()
        if answer in ("j", "n"):
            return answer == "j"
        print("Bitte j oder n eingeben.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, help="INI-Pfad; Standard unter config neben dem Skript")
    select = parser.add_mutually_exclusive_group()
    select.add_argument("--cycle", type=int, choices=range(1, 21), help="Einzelnen Temperaturzyklus waehlen")
    select.add_argument("--load", action="store_true", help="Separaten gemeinsamen Load-Zyklus waehlen")
    select.add_argument("--all", action="store_true", help="Alle 20 Temperaturplaetze nacheinander uebernehmen")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--stage", action="store_true")
    mode.add_argument("--cancel", action="store_true", help="Offenen Kandidaten verwerfen; aktives Profil bleibt")
    parser.add_argument("--net-id", default="192.168.213.249.1.1")
    parser.add_argument("--port", type=int, default=856)
    parser.add_argument("--symbol-root", default=ROOT)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    connection = None
    write_attempted = False
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0 or not 1 <= args.port <= 65535:
            raise ValueError("Timeout/Port ungueltig")
        payload = None
        if not args.status and not args.cancel:
            path = args.file or CONFIG / ("LoadCycleConfig.ini" if args.load else "TestCycleConfig.ini")
            if args.load:
                payload = load_load_cycle(path)
                print(f"Datei: {path.resolve()}; Load gueltig: {payload['Name']}")
            else:
                profiles = load_profiles(path)
                print(f"Datei: {path.resolve()}; 20 Plaetze gueltig, {sum(p['Enabled'] for p in profiles)} aktiviert")
                if args.cycle is not None:
                    payload = profiles[args.cycle-1]
                    print(f"Config{args.cycle}: {'aktiviert' if payload['Enabled'] else 'DEAKTIVIERT'}; {payload['Name']}")
                if args.stage and payload is None and not args.all:
                    raise ValueError("Fuer --stage --cycle 1..20 oder --all waehlen")
        if not (args.status or args.stage or args.cancel):
            print("OFFLINE: keine Verbindung. --status liest; --stage uebertraegt.")
            return 0
        import pyads
        print(f"ADS-Ziel {args.net_id}:{args.port}; {args.symbol_root}")
        connection = pyads.Connection(args.net_id, args.port)
        connection.open()
        transport = Transport(connection, pyads, args.symbol_root)
        if transport.read("TransferCapacity", "UINT") != 20:
            raise RuntimeError("PLC ist nicht der 20er-Empfaenger; kein Schreibzugriff")
        if args.status:
            for name, value in transport.status().items():
                print(f"{name}: {value}")
            for slot in range(1, 21):
                print(f"Profil {slot}: Version {transport.read('ActiveProfileVersion['+str(slot)+']', 'UDINT')}, "
                      f"extern gueltig {transport.read('Profiles['+str(slot)+'].Valid', 'BOOL')}")
            print(f"Load: Version {transport.read('ActiveLoadVersion', 'UDINT')}")
            return 0
        if args.cancel:
            if input("Offenen Kandidaten verwerfen? Exakt ABBRECHEN eingeben: ").strip() != "ABBRECHEN":
                return 0
            request = new_request(transport)
            write_attempted = True
            transport.write("CancelRequest", request, "UDINT")
            wait_for(transport, lambda s: s["CancelAcknowledged"] == request and not s["Error"],
                     args.timeout, ignore_error=True)
            print("Kandidat verworfen; aktiver Bestand unveraendert.")
            return 0
        if args.all:
            print("Sammelauftrag: 20 Einzeluebernahmen, keine atomare Bibliotheksuebernahme.")
            disabled = [p["Slot"] for p in profiles if not p["Enabled"]]
            print(f"Deaktiviert werden die Plaetze: {disabled}. Load bleibt separat.")
            confirmed = confirm_accept("Alle 20 uebernehmen?")
            write_attempted = confirmed
            transfer_all(transport, profiles, args.timeout, confirmed)
            return 0
        write_attempted = True
        request, version = stage(transport, payload, args.timeout)
        print(f"Kandidat validiert: Transfer {request}, Version {version}; noch nicht uebernommen.")
        if payload.get("Enabled") is False:
            print(f"ACHTUNG: Uebernahme deaktiviert Config{payload['Slot']} fuer neue Tests.")
        if not confirm_accept("Aktivieren fuer neue Tests?"):
            print("Kandidat bleibt bereit. Zum Verwerfen --cancel verwenden.")
            return 0
        accept(transport, payload, request, version, args.timeout)
        print(f"PLC bestaetigt Uebernahme: Version {version}. Laufende Tests behalten ihre Profile.")
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"ABBRUCH: {exc}")
        if write_attempted:
            print("Schreibzugriff versucht: Zustand mit --status pruefen; keine automatische Wiederholung.")
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
