"""Local catalog validation and simulated handover. No ADS or network access."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / "config" / "DeviceCatalog.ini"
FIELDS = {"Kind", "ID", "Name", "Serial", "Type", "Info", "Enabled"}


def validate_text(text):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ValueError(f"INI: {exc}") from exc
    if parser.defaults():
        raise ValueError("[DEFAULT] ist nicht erlaubt")
    if "Defaults" not in parser:
        raise ValueError("[Defaults] fehlt")
    defaults = {}
    expected_defaults = {f"Pos{p}_{field}" for p in range(1, 4) for field in ("DUT", "ECU", "ECU_Channel")}
    if set(parser["Defaults"]) != expected_defaults:
        raise ValueError("Defaults: unerwartete oder fehlende Felder")
    for key, value in parser["Defaults"].items():
        try:
            defaults[key] = int(value)
        except ValueError as exc:
            raise ValueError(f"Defaults.{key}: keine ganze Zahl") from exc
    entries = {"DUT": [], "ECU": []}
    for section in parser.sections():
        if section == "Defaults":
            continue
        values = parser[section]
        if set(values) != FIELDS:
            raise ValueError(f"{section}: unerwartete oder fehlende Felder")
        kind = values["Kind"]
        try:
            identity = int(values["ID"])
        except ValueError as exc:
            raise ValueError(f"{section}: ID muss ganzzahlig sein") from exc
        if kind not in entries or not 1 <= identity <= 25:
            raise ValueError(f"{section}: Kind oder ID ungueltig (1..25)")
        if section != f"{kind}_{identity:03d}":
            raise ValueError(f"{section}: Abschnitt passt nicht zu Kind/ID")
        if values["Enabled"] not in ("0", "1"):
            raise ValueError(f"{section}: Enabled muss 0 oder 1 sein")
        for field, limit in (("Name", 40), ("Serial", 40), ("Type", 40), ("Info", 120)):
            value = values[field]
            # Encoding of future PLC transport is not yet agreed. ASCII is the
            # deliberately conservative subset for this offline prototype.
            if not value.isascii() or any(ord(char) < 32 for char in value):
                raise ValueError(f"{section}.{field}: vorerst nur druckbares ASCII erlaubt")
            if len(value.encode("ascii")) > limit:
                raise ValueError(f"{section}.{field}: maximal {limit} Bytes")
            if field != "Info" and not value:
                raise ValueError(f"{section}.{field}: darf nicht leer sein")
        entries[kind].append({"ID": identity, "Enabled": values["Enabled"] == "1",
                              "Key": section, "Name": values["Name"], "Serial": values["Serial"],
                              "DeviceType": values["Type"], "Info": values["Info"]})
    for kind, items in entries.items():
        if not items or len(items) > 25 or len({item["ID"] for item in items}) != len(items):
            raise ValueError(f"{kind}: 1..25 eindeutige Eintraege erforderlich")
        items.sort(key=lambda item: item["ID"])
    for p in range(1, 4):
        dut, ecu, channel = (defaults[f"Pos{p}_{f}"] for f in ("DUT", "ECU", "ECU_Channel"))
        if dut == 0:
            if ecu != 0 or channel != 0:
                raise ValueError(f"Pos{p}: leer erfordert 0/0/0")
        elif channel not in (1, 2) or any(not any(e["ID"] == selected and e["Enabled"] for e in entries[kind])
                                            for kind, selected in (("DUT", dut), ("ECU", ecu))):
            raise ValueError(f"Pos{p}: ungueltige Default-Auswahl")
    occupied = [p for p in range(1, 4) if defaults[f"Pos{p}_DUT"] != 0]
    if len({defaults[f"Pos{p}_DUT"] for p in occupied}) != len(occupied):
        raise ValueError("Defaults: doppelte DUT-ID")
    if len({(defaults[f"Pos{p}_ECU"], defaults[f"Pos{p}_ECU_Channel"]) for p in occupied}) != len(occupied):
        raise ValueError("Defaults: doppelter ECU-Kanal")
    return {"Schema": "DeviceCatalog-DryRun-1", "Defaults": defaults, **entries}


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class SimulatedPLC:
    """Model only: no actual PLC protocol, symbols, persistence or transport."""
    def __init__(self):
        self.candidate = None
        self.active = None
        self.running_identity = {"DUTID": 1, "Name": "Frozen example identity"}

    def stage(self, payload):
        # Serialize-copy prevents caller mutations changing staged data.
        self.candidate = json.loads(json.dumps(payload))

    def accept(self, expected_digest):
        if self.candidate is None or fingerprint(self.candidate) != expected_digest:
            raise ValueError("Kandidat fehlt oder Pruefsumme stimmt nicht")
        self.active = self.candidate
        self.candidate = None


def self_test(text):
    payload = validate_text(text)
    cases = [
        ("doppelte Sektion", text + "\n[DUT_001]\n"),
        ("ID ausserhalb Bereich", text.replace("ID=1\n", "ID=26\n", 1)),
        ("Name zu lang", text.replace("Name=Sample DUT 1\n", "Name=" + "X" * 41 + "\n", 1)),
        ("Enabled ungueltig", text.replace("Enabled=1", "Enabled=2", 1)),
        ("leer mit ECU", text.replace("Pos1_ECU=0", "Pos1_ECU=1", 1)),
    ]
    for label, invalid in cases:
        try:
            validate_text(invalid)
        except ValueError:
            print(f"PASS: {label} abgewiesen")
        else:
            raise AssertionError(f"Nicht abgewiesen: {label}")
    plc = SimulatedPLC()
    plc.stage(payload)
    frozen = dict(plc.running_identity)
    if plc.active is not None:
        raise AssertionError("Staging aktivierte Katalog")
    try:
        plc.accept("wrong-digest")
    except ValueError:
        pass
    else:
        raise AssertionError("Falsche Pruefsumme akzeptiert")
    if plc.active is not None:
        raise AssertionError("Fehler veraenderte aktiven Katalog")
    plc.accept(fingerprint(payload))
    if plc.running_identity != frozen:
        raise AssertionError("Laufende Identitaet veraendert")
    previous = plc.active
    try:
        raise ConnectionError("Simulierter Transferabbruch vor Abschluss")
    except ConnectionError:
        pass
    if plc.active != previous:
        raise AssertionError("Transferabbruch veraenderte aktiven Katalog")
    print("PASS: Staging, bewusste Uebernahme, Pruefsummenfehler, eingefrorene Identitaet")
    print("Hinweis: Transferabbruch ist nur ein Modellfall, kein ADS-Verbindungstest.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--output", type=Path, help="Optionaler JSON-Kandidat; Quelldatei wird nie ueberschrieben")
    parser.add_argument("--simulate-accept", action="store_true", help="Bewusste Uebernahme im lokalen Modell")
    parser.add_argument("--self-test", action="store_true", help="Fehlerfaelle lokal pruefen")
    args = parser.parse_args()
    try:
        text = args.file.read_text(encoding="utf-8-sig")
        payload = validate_text(text)
        digest = fingerprint(payload)
        print(f"DRY RUN - kein ADS: {args.file.resolve()}")
        print(f"Katalog gueltig: {len(payload['DUT'])} DUTs, {len(payload['ECU'])} ECUs")
        print(f"SHA256: {digest}")
        print("Stammdaten enthalten gegebenenfalls Beispielnamen; Freigabe erfolgt fachlich.")
        plc = SimulatedPLC()
        plc.stage(payload)
        print("Simulierter Kandidat bereit; aktiver Katalog noch unveraendert.")
        if args.simulate_accept:
            plc.accept(digest)
            print("Simulierte Uebernahme erfolgreich; laufende Identitaet unveraendert.")
        if args.self_test:
            self_test(text)
        if args.output:
            if args.output.resolve() == args.file.resolve():
                raise ValueError("Output darf nicht die Quelldatei sein")
            with args.output.open("x", encoding="utf-8") as file:
                json.dump({"Digest": digest, "Payload": payload}, file, indent=2)
                file.write("\n")
            print(f"Neuer JSON-Kandidat: {args.output}")
    except (OSError, ValueError, AssertionError) as exc:
        print(f"FEHLER: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
