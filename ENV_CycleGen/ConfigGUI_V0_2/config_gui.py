"""Configuration editor/preview with explicit dry-run and online ADS modes."""
import copy
import json
import os
import queue
import threading
from tkinter import messagebox, ttk

from config_gui_dry_run import Application, tk
from ads_backend import Service
from pathlib import Path


class OnlineApplication(Application):
    def __init__(self, root, service=None):
        super().__init__(root)
        self.banner = root.winfo_children()[0]
        root.title('Prüfstand – Konfiguration · Dry Run / ADS')
        root.geometry('1100x900')
        self.service = service or Service()
        self.events = queue.Queue()
        self.busy = False
        self.online_candidate = None
        self.last_mode = 'Dry Run'
        self.mode = tk.StringVar(value='Dry Run')
        self.netid = tk.StringVar(value='192.168.213.249.1.1')
        self.port = tk.StringVar(value='856')
        self.connection_state = tk.StringVar(value='Offline · kein ADS-Zugriff')
        controls = ttk.Frame(root, padding=10)
        controls.pack(fill='x', before=root.winfo_children()[0])
        ttk.Label(controls, text='Modus:').pack(side='left')
        self.mode_widget = ttk.Combobox(controls, textvariable=self.mode, values=['Dry Run', 'Online ADS'],
                                       state='readonly', width=13)
        self.mode_widget.pack(side='left', padx=5)
        self.mode_widget.bind('<<ComboboxSelected>>', self.change_mode)
        ttk.Label(controls, text='AMS-NetId:').pack(side='left')
        ttk.Entry(controls, textvariable=self.netid, width=24).pack(side='left', padx=5)
        ttk.Label(controls, text='Port:').pack(side='left')
        ttk.Entry(controls, textvariable=self.port, width=6).pack(side='left', padx=5)
        ttk.Button(controls, text='PLC-Status lesen', command=self.status).pack(side='left', padx=6)
        ttk.Label(controls, textvariable=self.connection_state).pack(side='left', padx=6)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = root.after(80, self.poll)
        self.log('Online-Zugriff nur bei Auswahl Online ADS und ausdrücklich ausgelöster Aktion.')
        self.path_settings = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TwinCAT_ConfigGUI' / 'config_paths.json'
        saved = {}
        if self.path_settings.is_file():
            try:
                saved = json.loads(self.path_settings.read_text(encoding='utf-8'))
                if not isinstance(saved, dict):
                    saved = {}
            except (OSError, ValueError):
                self.log('Gespeicherte Dateipfade konnten nicht gelesen werden; Standardpfade verwenden.')
        existing = Path(r'C:\OPV\DVP_Tools\Tools\config')
        for kind, name in [('catalog', 'DeviceCatalog.ini'), ('profiles', 'TestCycleConfig.ini'), ('load', 'LoadCycleConfig.ini')]:
            chosen = saved.get(kind)
            self.paths[kind].set(chosen if isinstance(chosen, str) and chosen else str(existing/name))
        self.log('Konfigurationen aus Standardordner oder gespeicherter Auswahl. Kein Rueckfall auf Paketbeispiele.')
        labels = {'Simuliert übertragen': 'Simuliert übertragen und übernehmen',
                  'Auswahl simuliert übertragen': 'Auswahl simuliert übertragen und übernehmen',
                  'Alle 20 simuliert übertragen': 'Alle 20 simuliert übertragen und übernehmen'}
        for button in self.buttons:
            button.configure(text=labels.get(button.cget('text'), button.cget('text')))
        self.accept_button.pack_forget()
        self.action_button(self.pages['catalog'], 'Katalog bearbeiten ...', self.edit_catalog)

    def edit_catalog(self):
        from catalog_editor import CatalogEditor
        try:
            if self.busy:
                raise ValueError('Erst laufenden Auftrag abwarten')
            CatalogEditor(self)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Katalogeditor', str(exc))

    def browse(self, key):
        super().browse(key)
        try:
            self.path_settings.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path_settings.with_suffix('.tmp')
            temporary.write_text(json.dumps({kind: value.get() for kind, value in self.paths.items()}, indent=2), encoding='utf-8')
            temporary.replace(self.path_settings)
        except OSError as exc:
            self.log(f'Dateiauswahl gilt fuer diese Sitzung; Pfade konnten nicht gespeichert werden: {exc}')

    def target(self):
        parts = self.netid.get().strip().split('.')
        if len(parts) != 6 or any(not p.isdigit() or not 0 <= int(p) <= 255 for p in parts):
            raise ValueError('AMS-NetId benötigt sechs Zahlen von 0..255, z.B. 192.168.213.249.1.1.')
        port = int(self.port.get())
        if not 1 <= port <= 65535:
            raise ValueError('ADS-Port muss 1..65535 sein.')
        return ('.'.join(parts), port)

    def change_mode(self, event=None):
        if self.busy or self.online_candidate or self.store.candidate:
            self.mode.set(self.last_mode)
            messagebox.showwarning('Modus', 'Erst den laufenden Auftrag oder Kandidaten klären.')
            return
        self.last_mode = self.mode.get()
        online = self.mode.get() == 'Online ADS'
        self.banner.configure(text=('ONLINE ADS · Schreibzugriffe nur nach Bestätigung · Keine Kammer-Startbefehle'
                                    if online else 'DRY RUN · Keine SPS-Verbindung · INI-Speichern nur über den Editor'),
                              foreground='#a82020' if online else '#9b4300')
        self.connection_state.set('Online gewählt · noch keine Verbindung' if online else 'Offline · kein ADS-Zugriff')
        for button in self.buttons:
            text = button.cget('text')
            if online:
                labels = {
                    'Simuliert übertragen und übernehmen': 'Übertragen und übernehmen',
                    'Auswahl simuliert übertragen und übernehmen': 'Auswahl übertragen und übernehmen',
                    'Alle 20 simuliert übertragen und übernehmen': 'Alle 20 übertragen und übernehmen',
                }
            else:
                labels = {
                    'Übertragen und übernehmen': 'Simuliert übertragen und übernehmen',
                    'Auswahl übertragen und übernehmen': 'Auswahl simuliert übertragen und übernehmen',
                    'Alle 20 übertragen und übernehmen': 'Alle 20 simuliert übertragen und übernehmen',
                }
            button.configure(text=labels.get(text, text))
        self.accept_button.configure(text='In PLC übernehmen …' if online else 'Simuliert übernehmen …')
        self.tree.heading('version', text='Demo-Version' if not online else 'PLC-Version (Status)')
        for slot in self.tree.get_children():
            self.tree.set(slot, 'version', '—' if online else self.store.versions.get('profile:'+slot, 0))
        self.log('Modus: '+self.mode.get()+'. INI-Speichern bleibt eine lokale Aktion.')

    def read(self, kind):
        super().read(kind)
        if kind == 'profiles' and self.mode.get() == 'Online ADS':
            for slot in self.tree.get_children(): self.tree.set(slot, 'version', '—')

    def widgets(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.widgets(child)

    def run_job(self, title, operation, callback):
        if self.busy:
            return
        self.busy = True
        self.widget_states = []
        for widget in self.widgets(self.root):
            if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton)):
                self.widget_states.append((widget, widget.state()))
                widget.state(['disabled'])
        self.connection_state.set(title+' …')
        self.log(title+' gestartet.')
        def work():
            try:
                result = operation()
                self.events.put(('done', callback, result))
            except Exception as exc:
                self.events.put(('error', str(exc), None))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value, result = self.events.get_nowait()
                if kind == 'log':
                    self.log(value)
                    continue
                if kind == 'candidate':
                    self.online_candidate = value
                    self.pending.set('PLC-Prüfung erfolgreich · aktive Übernahme läuft.')
                    continue
                self.busy = False
                for widget, old in self.widget_states:
                    widget.state(['!disabled'] if 'disabled' not in old else ['disabled'])
                if kind == 'done':
                    self.connection_state.set('Auftrag abgeschlossen · Verbindung geschlossen')
                    try:
                        value(result)
                    except Exception as exc:
                        self.log('Anzeigefehler: '+str(exc))
                else:
                    self.connection_state.set('Fehler · Status prüfen')
                    detail = value
                    if 'No module named' in value and 'pyads' in value:
                        detail += '\npyads fehlt für diesen Python-Interpreter: py -m pip install pyads'
                    if '1808' in value:
                        detail += '\nPLC-Symbole/20er-Paket und aktiven Runtime-Port prüfen.'
                    if 'Missing ADS routes' in value:
                        detail += '\nADS-Route auf diesem Rechner und dem Ziel prüfen.'
                    self.log('ADS-Fehler: '+detail)
                    messagebox.showerror('ADS-Auftrag fehlgeschlagen', detail+
                        '\nBei versuchtem Schreiben Zustand per PLC-Status prüfen. Kein automatischer Retry.')
        except queue.Empty:
            pass
        self.timer = self.root.after(80, self.poll)

    def status(self):
        if self.mode.get() != 'Online ADS':
            messagebox.showinfo('Dry Run', 'Für echten Status zuerst Online ADS wählen.'); return
        try:
            target = self.target()
        except Exception as exc:
            messagebox.showerror('Ziel prüfen', str(exc)); return
        def show(result):
            self.log(f'PLC {target[0]}:{target[1]}: DeviceCatalog {result["catalog"]}')
            self.log('Zyklusempfänger: '+str(result['cycles']))
            if result['catalog'].get('Error'):
                self.log(self.service.describe_status('catalog', result['catalog']))
                self.log('Katalog-Empfaenger: '+result['catalog'].get('ReceiverHealth', 'unbekannt'))
            if result['cycles'].get('Error'):
                self.log(self.service.describe_status('cycles', result['cycles']))
                self.log('Zyklus-Empfaenger: '+result['cycles'].get('ReceiverHealth', 'unbekannt'))
            for slot, (version, valid) in enumerate(zip(result['versions'], result['valid']), 1):
                self.log(f'PLC Config{slot}: Version {version}, gültig {valid}')
                if self.tree.exists(str(slot)):
                    self.tree.set(str(slot), 'version', version)
            self.log('PLC Load-Version: '+str(result['load_version']))
            pending = self.online_candidate
            if pending and pending['target'] == target:
                state = result['catalog'] if pending['kind'] == 'catalog' else result['cycles']
                if state['AcceptedRequest'] == pending['request']:
                    self.online_candidate = None
                    self.pending.set('PLC bestätigt bereits erfolgte Übernahme; kein Kandidat bereit.')
                    self.log(self.pending.get())
        self.run_job('PLC-Status lesen', lambda: self.service.status(target), show)

    def stage(self, key):
        if self.mode.get() != 'Online ADS':
            if self.store.candidate:
                messagebox.showwarning('Demo-Auftrag', 'Bestehenden Demo-Kandidaten zuerst verwerfen.'); return
            if not messagebox.askyesno('Demo-Auftrag',
                    'Konfiguration simuliert übertragen, prüfen und übernehmen?\nKeine SPS-/ADS-Aktion.'):
                return
            super().stage(key)
            if self.store.candidate is not None:
                super().accept(confirm=False)
            return
        try:
            if self.online_candidate:
                raise ValueError('Ein Online-Kandidat ist bereit. Erst übernehmen/klären.')
            target = self.target()
            source = 'profiles' if key == 'all' else key
            if source not in self.loaded:
                raise ValueError('Zuerst INI einlesen und prüfen.')
            payload = copy.deepcopy(self.loaded[source])
            if key == 'profiles':
                selection = self.tree.selection()
                if not selection:
                    raise ValueError('Ein Profil auswählen.')
                payload = payload[int(selection[0])-1]
            detail = f'Ziel: {target[0]}:{target[1]}\nDatei: {self.paths[source].get()}\n'
            if key == 'all':
                disabled = [p['Slot'] for p in payload if not p['Enabled']]
                detail += (f'Alle 20 nacheinander übertragen UND übernehmen?\nDeaktiviert: {disabled}\n'
                           'Keine atomare Gesamtübernahme; Load bleibt separat.')
            else:
                detail += ('Konfiguration übertragen, durch die PLC prüfen und bei erfolgreicher Prüfung übernehmen?\n'
                           'Bei Prüfungsfehler keine Übernahme. Änderungen gelten für neue Tests.')
                if payload.get('Enabled') is False:
                    detail += '\nDieser Profilplatz wird bei Übernahme deaktiviert.'
            if not messagebox.askyesno('Online-Schreibauftrag', detail): return
        except Exception as exc:
            messagebox.showwarning('Übertragung', str(exc)); return
        if key == 'all':
            def progress(text): self.events.put(('log', text, None))
            self.run_job('20 Profile übertragen/übernehmen', lambda: self.service.all_profiles(target, payload, progress),
                         lambda slots: self.log('Bestätigte Plätze: '+str(slots)))
        else:
            kind = 'catalog' if key == 'catalog' else 'cycles'
            def staged(result):
                self.events.put(('candidate', result, None))
            def completed(result):
                self.online_candidate = None
                self.pending.set('Kein Kandidat bereit.')
                self.log(f'PLC bestätigt Übertragung, Prüfung und Übernahme: {source}, Version {result["version"]}.')
                if key == 'profiles':
                    self.tree.set(str(payload['Slot']), 'version', result['version'])
            self.run_job('Übertragen, prüfen und übernehmen',
                         lambda: self.service.transfer(target, kind, payload, staged), completed)

    def accept(self):
        if self.mode.get() != 'Online ADS': return super().accept()
        pending = self.online_candidate
        if not pending:
            messagebox.showinfo('Übernahme', 'Kein in dieser Sitzung bereitgestellter Kandidat. Status prüfen.'); return
        detail = (f'Kandidat in PLC übernehmen und für neue Tests aktivieren?\nZiel: {pending["target"]}\n'
                  f'Transfer {pending["request"]}, Version {pending["version"]}')
        if not messagebox.askyesno('PLC-Übernahme', detail): return
        def accepted(version):
            self.online_candidate = None
            self.pending.set('Kein Kandidat bereit.')
            self.log(f'PLC bestätigt Übernahme: Version {version}.')
        self.run_job('PLC-Übernahme', lambda: self.service.accept(pending), accepted)

    def discard(self):
        if self.mode.get() != 'Online ADS': return super().discard()
        if self.online_candidate and self.online_candidate['kind'] == 'catalog':
            messagebox.showinfo('DeviceCatalog', 'Dieser PLC-Empfänger hat keinen Cancel-Befehl. '
                'Kandidat bleibt bereit. Zustand über Status prüfen und nach PLC-Anleitung klären.'); return
        try:
            target = self.online_candidate['target'] if self.online_candidate else self.target()
        except Exception as exc:
            messagebox.showerror('Ziel', str(exc)); return
        if not messagebox.askyesno('PLC-Kandidat verwerfen', f'Offenen Zykluskandidaten auf {target} verwerfen?'): return
        def canceled(result):
            self.online_candidate = None
            self.pending.set('Kein Kandidat bereit.')
            self.log('PLC bestätigt Cancel; aktive Definitionen bleiben erhalten.')
        self.run_job('Zykluskandidat verwerfen', lambda: self.service.cancel(target), canceled)

    def edit(self, kind):
        if self.busy or self.online_candidate:
            messagebox.showwarning('Editor', 'Zuerst Online-Auftrag/Kandidat klären.'); return
        return super().edit(kind)

    def close(self):
        if self.busy:
            messagebox.showwarning('Auftrag läuft', 'Bitte laufenden Auftrag abwarten. Fenster bleibt offen.'); return
        if self.online_candidate and not messagebox.askyesno('Offener PLC-Kandidat',
                'PLC-Kandidat bleibt nach Schließen bereit. Trotzdem schließen?'):
            return
        self.root.after_cancel(self.timer)
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    OnlineApplication(root)
    root.mainloop()
