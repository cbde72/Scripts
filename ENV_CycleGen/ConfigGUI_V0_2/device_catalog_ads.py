"""DeviceCatalog test client. Default offline; online modes require explicit flags."""
import argparse
import secrets
import time
from pathlib import Path

from device_catalog_dry_run import DEFAULT_FILE, fingerprint, validate_text

ROOT = "GVL_DeviceCatalogTransfer"
FIELDS = {"ID": "UINT", "Enabled": "BOOL", "Key": "STRING", "Name": "STRING",
          "Serial": "STRING", "DeviceType": "STRING", "Info": "STRING"}
STATUS = {"BeginAcknowledged": "UDINT", "ValidatedRequest": "UDINT",
          "AcceptedRequest": "UDINT", "Receiving": "BOOL", "Ready": "BOOL",
          "Error": "BOOL", "ErrorID": "UDINT", "ErrorKind": "UINT",
          "ErrorIndex": "UINT", "ActiveVersion": "UDINT"}


def describe_status(status):
    code = int(status.get('ErrorID', 0))
    meanings = {0xD001: 'Commit ohne passenden Begin', 0xD002: 'Kandidat beim Abschluss verändert',
                0xD003: 'Katalogversion muss steigen', 0xD004: 'ID stimmt nicht mit Arrayplatz überein',
                0xD005: 'Leerer Slot enthält Daten', 0xD006: 'Pflichtfeld fehlt',
                0xD007: 'Mindestens ein DUT- und ECU-Eintrag erforderlich',
                0xD008: 'Kein passender validierter Kandidat',
                0xD009: 'Reservierter DUT-/ECU-Eintrag darf nicht geändert werden'}
    return (f'DeviceCatalog: ErrorID=0x{code:04X} ({code}), '
            f'{meanings.get(code, "Fehlercode gegen aktuellen PLC-Empfänger prüfen")}; '
            f'Kind={status.get("ErrorKind")}, Index={status.get("ErrorIndex")}; Status={status}')


def candidate_values(payload, version):
    yield "Candidate.Version", version, "UDINT"
    for kind in ("DUT", "ECU"):
        entries = {entry["ID"]: entry for entry in payload[kind]}
        for index in range(1, 26):
            entry = entries.get(index, {key: (False if key == "Enabled" else
                                           0 if key == "ID" else "") for key in FIELDS})
            for field, datatype in FIELDS.items():
                yield f"Candidate.{kind}[{index}].{field}", entry[field], datatype


class Transport:
    def __init__(self, connection, pyads, root):
        self.connection, self.pyads, self.root = connection, pyads, root

    def read(self, name, datatype):
        return self.connection.read_by_name(f"{self.root}.{name}",
                                            getattr(self.pyads, f"PLCTYPE_{datatype}"))

    def write(self, name, value, datatype):
        self.connection.write_by_name(f"{self.root}.{name}", value,
                                      getattr(self.pyads, f"PLCTYPE_{datatype}"))

    def status(self):
        return {name: self.read(name, datatype) for name, datatype in STATUS.items()}


def wait_for(transport, predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = transport.status()
        if status["Error"]:
            raise RuntimeError(describe_status(status))
        if predicate(status):
            return status
        time.sleep(0.1)
    raise TimeoutError("Keine passende PLC-Quittierung. Zustand mit --status pruefen; kein automatischer Retry.")


def stage(transport, payload, timeout):
    initial = transport.status()
    if initial["Receiving"] or initial["Ready"]:
        raise RuntimeError("Ein Kandidat/Transfer ist bereits offen. Erst dessen Zustand klaeren.")
    if initial["Error"]:
        raise RuntimeError(describe_status(initial) + '; bestehenden Zustand zuerst klären.')
    version = initial["ActiveVersion"] + 1
    if not 1 < version <= 0xFFFFFFFF:
        raise RuntimeError("ActiveVersion nicht initialisiert oder Versionsbereich erschoepft.")
    used = {transport.read(name, "UDINT") for name in
            ("BeginRequest", "CommitRequest", "AcceptRequest", "BeginAcknowledged",
             "ValidatedRequest", "AcceptedRequest")}
    request = secrets.randbelow(0xFFFFFFFF) + 1
    while request in used:
        request = secrets.randbelow(0xFFFFFFFF) + 1
    values = list(candidate_values(payload, version))
    transport.write("BeginRequest", request, "UDINT")
    wait_for(transport, lambda s: s["BeginAcknowledged"] == request and s["Receiving"], timeout)
    for name, value, datatype in values:
        transport.write(name, value, datatype)
    for name, value, datatype in values:
        if transport.read(name, datatype) != value:
            raise RuntimeError(f"Rueckleseabweichung: {name}; kein Commit gesendet.")
    current = transport.status()
    if current['Error']:
        raise RuntimeError(describe_status(current))
    if current["BeginAcknowledged"] != request or not current["Receiving"] or current["Error"]:
        raise RuntimeError("Empfangszustand wurde veraendert; kein Commit gesendet.")
    transport.write("CommitRequest", request, "UDINT")
    wait_for(transport, lambda s: s["ValidatedRequest"] == request and s["Ready"], timeout)
    return request, version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="Online: nur Rueckmeldungen lesen")
    mode.add_argument("--stage", action="store_true", help="Online: Kandidat schreiben; Uebernahme separat bestaetigen")
    parser.add_argument("--net-id", default="192.168.213.249.1.1")
    parser.add_argument("--port", type=int, default=856)
    parser.add_argument("--symbol-root", default=ROOT)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    connection = None
    try:
        if args.timeout <= 0 or not 1 <= args.port <= 65535:
            raise ValueError("Timeout/Port ungueltig")
        payload = None
        if not args.status:
            payload = validate_text(args.file.read_text(encoding="utf-8-sig"))
            print(f"Datei: {args.file.resolve()}")
            print(f"Gueltig: {len(payload['DUT'])} DUTs, {len(payload['ECU'])} ECUs; SHA256 {fingerprint(payload)}")
        if not args.status and not args.stage:
            print("OFFLINE: keine Verbindung. --status liest online; --stage schreibt den Kandidaten.")
            return 0
        import pyads
        print(f"ADS-Ziel: {args.net_id}:{args.port}; Symbole: {args.symbol_root}")
        connection = pyads.Connection(args.net_id, args.port)
        connection.open()
        transport = Transport(connection, pyads, args.symbol_root)
        if args.status:
            for name, value in transport.status().items():
                print(f"{name}: {value}")
            return 0
        request, version = stage(transport, payload, args.timeout)
        print(f"Kandidat validiert: Transfer {request}, Version {version}. Noch nicht uebernommen.")
        print("Defaults werden nicht uebertragen. Reservierte Eintraege duerfen nicht geaendert werden.")
        if input("Fuer aktive Uebernahme exakt UEBERNEHMEN eingeben, sonst Enter: ").strip() != "UEBERNEHMEN":
            print("Nicht uebernommen. Kandidat bleibt in der PLC bereit; --status zeigt seinen Zustand.")
            return 0
        state = transport.status()
        if state["Error"] or not state["Ready"] or state["ValidatedRequest"] != request:
            raise RuntimeError("Kandidat nicht mehr bereit; keine Uebernahme angefordert.")
        transport.write("AcceptRequest", request, "UDINT")
        result = wait_for(transport, lambda s: s["AcceptedRequest"] == request, args.timeout)
        if result["ActiveVersion"] != version:
            raise RuntimeError("Quittierte Version stimmt nicht; Zustand manuell pruefen.")
        print(f"PLC bestaetigt Uebernahme: Version {version}, Transfer {request}.")
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"ABBRUCH: {exc}")
        print("Online-Abbruch kann einen offenen oder bereits angenommenen Transfer hinterlassen. --status pruefen.")
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
