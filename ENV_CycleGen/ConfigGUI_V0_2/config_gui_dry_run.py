"""Local configuration GUI with explicit INI editing. No ADS/network/PLC access."""
import copy
import configparser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from device_catalog_dry_run import validate_text
from cycle_transfer_ads import ini_parser, load_profiles, load_load_cycle

HERE = Path(__file__).resolve().parent
TITLES = {'catalog': 'DeviceCatalog', 'profiles': 'Temperaturprofile', 'load': 'Load-Zyklus'}


def curve_vertices(points, duration, stepped=False):
    """Setpoint trajectory including hold to end; digital transitions are vertical."""
    if not points:
        return []
    result = [(points[0]['Time_s'], points[0]['Value'])]
    for point in points[1:]:
        if stepped:
            result.append((point['Time_s'], result[-1][1]))
        result.append((point['Time_s'], point['Value']))
    if result[-1][0] < duration:
        result.append((duration, result[-1][1]))
    return result


class SetpointPlot(ttk.Frame):
    def __init__(self, parent, height=260):
        super().__init__(parent)
        self.title = ttk.Label(self, text='Sollwertvorschau: zuerst eine INI einlesen.')
        self.title.pack(anchor='w')
        self.canvas = tk.Canvas(self, height=height, background='white', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.data = None
        self.canvas.bind('<Configure>', lambda event: self.draw())

    def clear(self):
        self.data = None
        self.title.configure(text='Sollwertvorschau: zuerst eine INI einlesen.')
        self.canvas.delete('all')

    def show(self, name, duration, curves, enabled=True):
        self.data = (duration, curves)
        self.title.configure(text=f'{name} · {duration} s · Sollwerte aus INI'+(' · DEAKTIVIERT' if not enabled else ''))
        self.draw()

    def draw(self):
        canvas = self.canvas
        canvas.delete('all')
        if self.data is None:
            return
        duration, curves = self.data
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 180)
        left, right = 76, width-18
        row_height = height/len(curves)
        for row, (label, points, stepped, color) in enumerate(curves):
            top, bottom = row*row_height+23, (row+1)*row_height-27
            values = [p['Value'] for p in points]
            if stepped:
                low, high = -0.1, 100 #1.1
            elif label.startswith(('Feuchte', 'Lift')):
                low, high = 0, 100
            else:
                low, high = min(values), max(values)
                pad = max((high-low)*0.1, 1)
                low, high = low-pad, high+pad
            def xy(stamp, value):
                return left+(right-left)*stamp/duration, bottom-(bottom-top)*(value-low)/(high-low)
            canvas.create_text(left, top-12, text=label, anchor='w', fill=color)
            for fraction in (0, 0.5, 1):
                value = low+(high-low)*fraction
                y = xy(0, value)[1]
                canvas.create_line(left, y, right, y, fill='#e3e7ed')
                canvas.create_text(left-7, y, text=f'{value:.3g}', anchor='e', fill='#555555')
            for fraction in (0, 0.25, 0.5, 0.75, 1):
                stamp = duration*fraction
                x = xy(stamp, low)[0]
                canvas.create_line(x, top, x, bottom, fill='#e3e7ed')
                canvas.create_text(x, bottom+13, text=f'{stamp:g} s', fill='#555555')
            vertices = curve_vertices(points, duration, stepped)
            coords = [coordinate for stamp, value in vertices for coordinate in xy(stamp, value)]
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2)
            for point in points:
                x, y = xy(point['Time_s'], point['Value'])
                canvas.create_oval(x-3, y-3, x+3, y+3, fill=color, outline=color)


def detect_file_kind(path):
    sections = set(ini_parser(path).sections())
    matches = []
    if 'TestCycleConfig' in sections or any(s.startswith('Config') and s[6:].isdigit() for s in sections):
        matches.append('profiles')
    if sections & {'LoadCycleConfig', 'LoadCycle'}:
        matches.append('load')
    if 'Defaults' in sections or any(s.startswith(('DUT_', 'ECU_')) for s in sections):
        matches.append('catalog')
    if len(matches) != 1:
        raise ValueError('Dateiart nicht eindeutig erkannt. Erwartet werden DeviceCatalog.ini, '
                         'TestCycleConfig.ini oder LoadCycleConfig.ini. Bitte INI-Abschnitte prüfen.')
    return matches[0]


class DemoStore:
    """In-memory UI model, not an emulator of the PLC's ADS protocol."""
    def __init__(self):
        self.active = {}
        self.versions = {}
        self.candidate = None

    def stage(self, entries):
        if self.candidate is not None:
            raise ValueError('Es ist bereits ein Kandidat offen. Erst übernehmen oder verwerfen.')
        self.candidate = copy.deepcopy(entries)

    def accept(self):
        if self.candidate is None:
            raise ValueError('Kein Kandidat bereit.')
        for key, payload in self.candidate.items():
            self.active[key] = copy.deepcopy(payload)
            self.versions[key] = self.versions.get(key, 0) + 1
        result = list(self.candidate)
        self.candidate = None
        return result

    def discard(self):
        self.candidate = None


class Application:
    def __init__(self, root):
        self.root = root
        self.store = DemoStore()
        self.loaded = {}
        self.paths = {}
        self.buttons = []
        self.profile_previews = {}
        root.title('Prüfstand – Konfiguration · DRY RUN')
        root.geometry('1050x780')
        root.minsize(800, 650)
        ttk.Label(root, text='DRY RUN · Keine SPS-Verbindung · INI-Speichern nur über den Editor',
                  foreground='#9b4300', font=('Segoe UI', 11, 'bold')).pack(padx=14, pady=12, anchor='w')
        book = ttk.Notebook(root)
        self.book = book
        self.pages = {}
        book.pack(fill='both', expand=True, padx=14)
        for key, title, filename in [('catalog', 'DeviceCatalog', 'DeviceCatalog.ini'),
                                     ('profiles', 'Temperaturprofile', 'TestCycleConfig.ini'),
                                     ('load', 'Load-Zyklus', 'LoadCycleConfig.ini')]:
            page = ttk.Frame(book, padding=10)
            self.pages[key] = page
            book.add(page, text=title)
            variable = tk.StringVar(value=str(HERE/'config'/filename))
            self.paths[key] = variable
            line = ttk.Frame(page)
            line.pack(fill='x')
            entry = ttk.Entry(line, textvariable=variable)
            entry.pack(side='left', fill='x', expand=True)
            variable.trace_add('write', lambda *args, k=key: self.invalidate(k))
            ttk.Button(line, text='Datei wählen', command=lambda k=key: self.browse(k)).pack(side='left', padx=5)
            ttk.Button(line, text='Einlesen / prüfen', command=lambda k=key: self.read(k)).pack(side='left')
            if key == 'profiles':
                self.tree = ttk.Treeview(page, columns=('slot', 'name', 'enabled', 'duration', 'version'),
                                         show='headings', selectmode='browse', height=6)
                for name, label, width in [('slot', 'Config', 65), ('name', 'Name in der INI', 310),
                                           ('enabled', 'INI aktiviert', 100), ('duration', 'Dauer [s]', 90),
                                           ('version', 'Demo-Version', 110)]:
                    self.tree.heading(name, text=label)
                    self.tree.column(name, width=width)
                self.tree.pack(fill='both', expand=True, pady=10)
                self.profile_plot = SetpointPlot(page, height=285)
                self.profile_plot.pack(fill='both', expand=True, pady=(0, 8))
                self.tree.bind('<<TreeviewSelect>>', lambda event: self.show_profile())
                actions = ttk.Frame(page)
                actions.pack(fill='x')
                self.action_button(actions, 'Auswahl simuliert übertragen', lambda: self.stage('profiles'))
                self.action_button(actions, 'Alle 20 simuliert übertragen', lambda: self.stage('all'))
                self.action_button(actions, 'Auswahl bearbeiten …', lambda: self.edit('profiles'))
            else:
                preview = tk.Text(page, height=12, wrap='word', state='disabled')
                preview.pack(fill='both', expand=True, pady=10)
                setattr(self, key+'_preview', preview)
                if key == 'load':
                    preview.configure(height=4)
                    self.load_plot = SetpointPlot(page, height=210)
                    self.load_plot.pack(fill='both', expand=True, pady=(0, 8))
                self.action_button(page, 'Simuliert übertragen', lambda k=key: self.stage(k))
                if key == 'load':
                    self.action_button(page, 'Load bearbeiten …', lambda: self.edit('load'))
        actions = ttk.Frame(root, padding=14)
        actions.pack(fill='x')
        self.pending = tk.StringVar(value='Kein Kandidat bereit.')
        ttk.Label(actions, textvariable=self.pending).pack(side='left', expand=True, fill='x')
        self.accept_button = ttk.Button(actions, text='Simuliert übernehmen …', command=self.accept)
        self.accept_button.pack(side='left', padx=6)
        ttk.Button(actions, text='Kandidat verwerfen', command=self.discard).pack(side='left')
        self.logbox = tk.Text(root, height=9, state='disabled', wrap='word')
        self.logbox.pack(fill='both', padx=14, pady=(0, 14))
        self.log('Demo bereit. INIs einlesen, Kandidaten simulieren und bewusst übernehmen.')
        self.log('Version 0 = noch keine Demo-Übernahme. Kein PLC-Status, keine Persistenz.')

    def action_button(self, parent, title, command):
        button = ttk.Button(parent, text=title, command=command)
        button.pack(side='left', padx=(0, 8))
        self.buttons.append(button)

    def log(self, text):
        self.logbox.configure(state='normal')
        self.logbox.insert('end', datetime.now().strftime('%H:%M:%S')+' · '+text+'\n')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def invalidate(self, key):
        self.loaded.pop(key, None)
        if key == 'profiles' and hasattr(self, 'tree'):
            self.tree.delete(*self.tree.get_children())
            self.profile_previews = {}
            self.profile_plot.clear()
        if key == 'load' and hasattr(self, 'load_plot'):
            self.load_plot.clear()
        preview = getattr(self, key+'_preview', None)
        if preview is not None:
            preview.configure(state='normal')
            preview.delete('1.0', 'end')
            preview.configure(state='disabled')

    def browse(self, key):
        path = filedialog.askopenfilename(filetypes=[('INI-Dateien', '*.ini'), ('Alle Dateien', '*.*')])
        if path:
            self.paths[key].set(path)

    def show_profile(self):
        selection = self.tree.selection()
        if not selection:
            return
        preview = self.profile_previews.get(int(selection[0]))
        if preview is None:
            self.profile_plot.clear()
            self.profile_plot.title.configure(text='Keine Sollwertvorlage für diesen Platz vorhanden.')
            return
        name, duration, curves, enabled = preview
        self.profile_plot.show(name, duration, curves, enabled)

    def edit(self, kind):
        try:
            if self.store.candidate is not None:
                raise ValueError('Vor dem Bearbeiten den offenen Kandidaten übernehmen oder verwerfen.')
            if kind not in self.loaded:
                raise ValueError('Zuerst die INI einlesen und prüfen.')
            slot = None
            if kind == 'profiles':
                selection = self.tree.selection()
                if not selection:
                    raise ValueError('Zuerst ein Profil auswählen.')
                slot = int(selection[0])
            from profile_editor import ProfileEditor
            ProfileEditor(self, kind, slot, SetpointPlot)
        except Exception as exc:
            messagebox.showerror('Editor konnte nicht geöffnet werden', str(exc))

    def read(self, key):
        self.invalidate(key)
        try:
            path = Path(self.paths[key].get())
            kind = detect_file_kind(path)
            if kind != key:
                detail = (f'Die Datei „{path.name}“ enthält {TITLES[kind]}, '
                          f'keinen Inhalt für den Reiter {TITLES[key]}.\n\n'
                          f'Zum Reiter „{TITLES[kind]}“ wechseln und dort prüfen?')
                self.log(f'Andere Dateiart erkannt: {path.name} → {TITLES[kind]}.')
                if messagebox.askyesno('Datei gehört zu einem anderen Reiter', detail):
                    self.paths[kind].set(str(path))
                    self.book.select(self.pages[kind])
                    self.read(kind)
                return
            if key == 'catalog':
                payload = validate_text(path.read_text(encoding='utf-8-sig'))
                summary = f"{len(payload['DUT'])} DUTs, {len(payload['ECU'])} ECUs\n"
                for kind in ('DUT', 'ECU'):
                    summary += '\n'+kind+'\n'+'\n'.join(f"{p['ID']:02}: {p['Name']} · {p['Serial']}" for p in payload[kind])+'\n'
            elif key == 'profiles':
                payload = load_profiles(path)
                parser = ini_parser(path)
                self.profile_previews = {}
                for p in payload:
                    slot = p['Slot']
                    section = parser[f'Config{slot}']
                    prefix = f'Config{slot}_'
                    if prefix+'Duration' not in section:
                        continue
                    curves = []
                    for field, label, stepped, color in [('Temperature', 'Temperatur [°C]', False, '#c54a30'),
                            ('Humidity', 'Feuchte [%]', False, '#2679b8'), ('Operation', 'Operation Mode [0/1]', True, '#498447')]:
                        points = [{'Time_s': int(section[prefix+f'{field}{i:02}_Time']),
                                   'Value': float(section[prefix+f'{field}{i:02}_Set'])}
                                  for i in range(1, int(section[prefix+field+'Points'])+1)]
                        curves.append((label, points, stepped, color))
                    self.profile_previews[slot] = (section[prefix+'Name'], int(section[prefix+'Duration']), curves, p['Enabled'])
                rows = [(p['Slot'], parser[f"Config{p['Slot']}"] , p['Enabled']) for p in payload]
                self.tree.delete(*self.tree.get_children())
                for slot, section, enabled in rows:
                    self.tree.insert('', 'end', iid=str(slot), values=(slot, section.get(f'Config{slot}_Name', 'Nicht definiert'),
                        'Ja' if enabled else 'Nein', section.get(f'Config{slot}_Duration', '—'), self.store.versions.get(f'profile:{slot}', 0)))
                self.tree.selection_set('1')
                self.show_profile()
                summary = '20 Plätze geprüft; '+str(sum(p['Enabled'] for p in payload))+' aktiviert.'
            else:
                payload = load_load_cycle(path)
                summary = payload['Name']+f"\nDauer: {payload['Duration_s']} s\nLift-Punkte:\n"
                summary += '\n'.join(f"{p['Time_s']} s → {p['Value']} %" for p in payload['Lift'])
                self.load_plot.show(payload['Name'], payload['Duration_s'], [('Lift [%]', payload['Lift'], True, '#8150aa')])
            if key != 'profiles':
                box = getattr(self, key+'_preview')
                box.configure(state='normal'); box.delete('1.0', 'end'); box.insert('end', summary); box.configure(state='disabled')
            self.loaded[key] = payload
            self.log(f'{path.name}: gültig eingelesen. Änderungen danach erfordern erneutes Einlesen.')
        except Exception as exc:
            if isinstance(exc, FileNotFoundError):
                help_text = 'Datei nicht gefunden. Bitte über „Datei wählen“ einen vorhandenen Pfad auswählen.'
            elif isinstance(exc, PermissionError):
                help_text = 'Kein Lesezugriff auf die Datei. Bitte Zugriffsrechte oder einen anderen Ordner prüfen.'
            elif isinstance(exc, KeyError):
                help_text = f'Pflichtfeld oder Abschnitt fehlt: {exc}. Bitte mit der passenden Beispiel-INI vergleichen.'
            elif isinstance(exc, configparser.Error):
                help_text = 'INI-Syntaxfehler, beispielsweise ein doppelter Abschnitt oder Schlüssel. '+str(exc)
            else:
                help_text = str(exc)
            detail = f'Reiter: {TITLES[key]}\nDatei: {self.paths[key].get()}\n\n{help_text}'
            self.log('Dateifehler: '+detail.replace('\n', ' · '))
            messagebox.showerror('Datei konnte nicht geprüft werden', detail)

    def stage(self, key):
        try:
            source = 'profiles' if key == 'all' else key
            if source not in self.loaded:
                raise ValueError('Zuerst die Datei einlesen und prüfen.')
            payload = self.loaded[source]
            if key == 'all':
                entries = {f"profile:{p['Slot']}": p for p in payload}
            elif key == 'profiles':
                selection = self.tree.selection()
                if not selection:
                    raise ValueError('Ein Profil auswählen.')
                slot = int(selection[0])
                entries = {f'profile:{slot}': payload[slot-1]}
            else:
                entries = {key: payload}
            self.store.stage(entries)
            self.pending.set('Demo-Kandidat bereit: '+', '.join(entries))
            self.log('Simuliert übertragen und geprüft: '+', '.join(entries))
        except ValueError as exc:
            messagebox.showwarning('Kandidat', str(exc))

    def accept(self, confirm=True):
        if self.store.candidate is None:
            messagebox.showinfo('Übernahme', 'Kein Kandidat bereit.')
            return
        disabled = [key for key, p in self.store.candidate.items() if p.get('Enabled') is False]
        detail = '\nDeaktivierte Plätze: '+', '.join(disabled) if disabled else ''
        if confirm and not messagebox.askyesno('Demo-Übernahme', 'Kandidaten im Demo-Arbeitsspeicher übernehmen?'+detail+
                                   '\nKeine Änderung an einer SPS oder Datei.'):
            self.log('Übernahme abgelehnt; Kandidat bleibt bereit.')
            return
        keys = self.store.accept()
        for key in keys:
            self.log(f'Demo übernommen: {key}, Version {self.store.versions[key]}')
            if key.startswith('profile:'):
                slot = key.split(':')[1]
                if self.tree.exists(slot):
                    self.tree.set(slot, 'version', self.store.versions[key])
        self.pending.set('Kein Kandidat bereit.')

    def discard(self):
        self.store.discard()
        self.pending.set('Kein Kandidat bereit.')
        self.log('Kandidat verworfen; Demo-Bestand unverändert.')


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == '__main__':
    main()
