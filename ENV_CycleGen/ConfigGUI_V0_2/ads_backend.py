"""ADS operations, independent of Tkinter; connections are scoped to each job."""
import copy
import time
from contextlib import contextmanager
import device_catalog_ads as catalog
import cycle_transfer_ads as cycles


@contextmanager
def connect(target, kind):
    import pyads
    connection = pyads.Connection(target[0], target[1])
    try:
        connection.open()
        module = catalog if kind == 'catalog' else cycles
        transport = module.Transport(connection, pyads, module.ROOT)
        if kind != 'catalog' and transport.read('TransferCapacity', 'UINT') != 20:
            raise ValueError('PLC ist nicht der 20er-Zyklusempfänger.')
        yield transport
    finally:
        connection.close()


class Service:
    def __init__(self, connector=connect):
        self.connector = connector

    @staticmethod
    def describe_status(kind, state):
        return (catalog if kind == 'catalog' else cycles).describe_status(state)

    @staticmethod
    def receiver_health(transport):
        try:
            first = transport.read('ReceiverHeartbeat', 'UDINT')
            time.sleep(0.05)
            second = transport.read('ReceiverHeartbeat', 'UDINT')
            return 'laeuft' if first != second else 'kein Fortschritt im 50-ms-Fenster; Task/Aufruf pruefen'
        except Exception as exc:
            return 'nicht verfuegbar (aeltere PLC oder Lesefehler): '+str(exc)

    def status(self, target):
        result = {}
        with self.connector(target, 'catalog') as transport:
            result['catalog'] = transport.status()
            result['catalog']['ReceiverHealth'] = self.receiver_health(transport)
        with self.connector(target, 'cycles') as transport:
            result['cycles'] = transport.status()
            result['cycles']['ReceiverHealth'] = self.receiver_health(transport)
            result['versions'] = [transport.read(f'ActiveProfileVersion[{slot}]', 'UDINT') for slot in range(1, 21)]
            result['valid'] = [transport.read(f'Profiles[{slot}].Valid', 'BOOL') for slot in range(1, 21)]
            result['load_version'] = transport.read('ActiveLoadVersion', 'UDINT')
        return result

    def stage(self, target, kind, payload):
        payload = copy.deepcopy(payload)
        with self.connector(target, kind) as transport:
            module = catalog if kind == 'catalog' else cycles
            request, version = module.stage(transport, payload, 15)
        return {'target': target, 'kind': kind, 'payload': payload, 'request': request, 'version': version}

    def accept(self, pending):
        target, kind, payload = pending['target'], pending['kind'], pending['payload']
        request, version = pending['request'], pending['version']
        with self.connector(target, kind) as transport:
            if kind != 'catalog':
                cycles.accept(transport, payload, request, version, 15)
            else:
                state = transport.status()
                if state['Error']:
                    raise ValueError(catalog.describe_status(state))
                if state['Error'] or not state['Ready'] or state['ValidatedRequest'] != request:
                    raise ValueError(f'Kein bereiter DeviceCatalog-Kandidat für Transfer {request}; Status={state}')
                transport.write('AcceptRequest', request, 'UDINT')
                catalog.wait_for(transport, lambda s: s['AcceptedRequest'] == request, 15)
                if transport.read('ActiveVersion', 'UDINT') != version:
                    raise ValueError('Quittierte Katalogversion stimmt nicht; Status prüfen.')
        return version

    def transfer(self, target, kind, payload, staged=None):
        """One confirmed user action; PLC validation must finish before AcceptRequest."""
        pending = self.stage(target, kind, payload)
        if staged is not None:
            staged(pending)
        self.accept(pending)
        return pending

    def cancel(self, target):
        with self.connector(target, 'cycles') as transport:
            request = cycles.new_request(transport)
            transport.write('CancelRequest', request, 'UDINT')
            cycles.wait_for(transport, lambda s: s['CancelAcknowledged'] == request and not s['Error'],
                            15, ignore_error=True)

    def all_profiles(self, target, profiles, progress):
        completed = []
        for payload in copy.deepcopy(profiles):
            slot = payload['Slot']
            try:
                pending = self.stage(target, 'cycles', payload)
                self.accept(pending)
            except Exception as exc:
                raise RuntimeError(f'Abbruch bei Config{slot}. Bestätigte Plätze: {completed}. '
                                   f'Aktuellen Platz per Status prüfen; kein Rollback. Ursache: {exc}') from exc
            completed.append(slot)
            progress(f'Config{slot}: Version {pending["version"]} bestätigt; '+
                     ('aktiviert' if payload['Enabled'] else 'deaktiviert'))
        return completed
