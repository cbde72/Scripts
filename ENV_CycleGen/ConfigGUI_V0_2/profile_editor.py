"""Local INI editing with validation, backups and external-change detection."""
import configparser
from datetime import datetime
import io
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import uuid

from cycle_transfer_ads import load_profiles, load_load_cycle


class TextSource:
    def __init__(self, text):
        self.text = text

    def read_text(self, **kwargs):
        return self.text


def replace_section(original, section, values, kind):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(original)
    if section not in parser:
        raise ValueError('Abschnitt fehlt: '+section)
    parser[section] = values
    result = io.StringIO()
    parser.write(result, space_around_delimiters=False)
    text = result.getvalue()
    if kind == 'profiles':
        load_profiles(TextSource(text))
    else:
        load_load_cycle(TextSource(text))
    return text


def save_section(path, expected_bytes, section, values, kind):
    path = Path(path)
    if path.read_bytes() != expected_bytes:
        raise ValueError('Die Datei wurde außerhalb des Editors geändert. Schließen und erneut einlesen.')
    text = replace_section(expected_bytes.decode('utf-8-sig'), section, values, kind)
    backup = path.with_name(path.name+'.'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.bak')
    temp_path = None
    try:
        # Validation precedes backup/write. Backup is the exact original bytes.
        with backup.open('xb') as file:
            file.write(expected_bytes)
        temp_path = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        with temp_path.open('xb') as file:
            file.write(text.encode('utf-8'))
            file.flush()
            os.fsync(file.fileno())
        if path.read_bytes() != expected_bytes:
            raise ValueError('Die Datei wurde inzwischen geändert. Nicht gespeichert; bitte erneut einlesen.')
        os.replace(str(temp_path), str(path))
        temp_path = None
        return backup
    finally:
        if temp_path is not None:
            temp_path.unlink()


class ProfileEditor:
    def __init__(self, app, kind, slot, plot_class):
        self.app, self.kind, self.slot = app, kind, slot
        self.path = Path(app.paths[kind].get())
        self.original = self.path.read_bytes()
        self.section = f'Config{slot}' if kind == 'profiles' else 'LoadCycle'
        self.prefix = f'Config{slot}_' if kind == 'profiles' else 'LoadCycle_'
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        parser.read_string(self.original.decode('utf-8-sig'))
        # Validate before opening, including other slots.
        if kind == 'profiles':
            load_profiles(TextSource(self.original.decode('utf-8-sig')))
        else:
            load_load_cycle(TextSource(self.original.decode('utf-8-sig')))
        section = parser[self.section]
        self.window = tk.Toplevel(app.root)
        self.window.title('INI bearbeiten · '+self.section+' · lokal')
        self.window.geometry('1050x820')
        self.window.minsize(900, 700)
        self.window.transient(app.root)
        self.window.grab_set()
        ttk.Label(self.window, text=str(self.path), wraplength=950).pack(anchor='w', padx=12, pady=8)
        form = ttk.Frame(self.window, padding=12)
        form.pack(fill='x')
        self.fields = {}
        specs = [('Name', 'Name', 'Neuer Zyklus'), ('Duration', 'Dauer [s]', '60')]
        if kind == 'profiles':
            specs += [('WaitTemperatureTolerance', 'Toleranz [K]', '0.0'),
                      ('WaitTemperatureStableTime', 'Stabilzeit [s]', '0')]
        for index, (field, label, default) in enumerate(specs):
            ttk.Label(form, text=label).grid(row=index//2, column=(index%2)*2, sticky='w', padx=5, pady=4)
            variable = tk.StringVar(value=section.get(self.prefix+field, default))
            self.fields[field] = variable
            ttk.Entry(form, textvariable=variable, width=36).grid(row=index//2, column=(index%2)*2+1, sticky='ew', padx=5)
        self.enabled = tk.BooleanVar(value=section.get(self.prefix+'Enabled', '0') == '1')
        self.wait = tk.BooleanVar(value=section.get(self.prefix+'WaitForTemperatureEnable', '0') == '1')
        if kind == 'profiles':
            ttk.Checkbutton(form, text='Profil aktiviert', variable=self.enabled).grid(row=2, column=0, columnspan=2, sticky='w')
            ttk.Checkbutton(form, text='Auf Temperatur warten', variable=self.wait).grid(row=2, column=2, columnspan=2, sticky='w')
        tabs = ttk.Notebook(self.window)
        tabs.pack(fill='both', expand=True, padx=12)
        self.curves = {}
        specs = [('Temperature', 'Temperatur [°C]', False, '#c54a30'), ('Humidity', 'Feuchte [%]', False, '#2679b8'),
                 ('Operation', 'Operation Mode [0/1]', True, '#498447')] if kind == 'profiles' else [('Lift', 'Lift [%]', False, '#8150aa')]
        self.specs = specs
        for field, label, stepped, color in specs:
            frame = ttk.Frame(tabs, padding=6)
            tabs.add(frame, text=label)
            tree = ttk.Treeview(frame, columns=('time', 'value'), show='headings', height=5, selectmode='browse')
            tree.heading('time', text='Zeit [s]'); tree.heading('value', text=label)
            tree.pack(fill='both', expand=True)
            count = int(section.get(self.prefix+field+'Points', '1'))
            default_value = '23.0' if field == 'Temperature' else '50.0' if field == 'Humidity' else '0.0'
            for index in range(1, count+1):
                tree.insert('', 'end', values=(section.get(self.prefix+f'{field}{index:02}_Time', '0'),
                                               section.get(self.prefix+f'{field}{index:02}_Set', default_value)))
            self.curves[field] = tree
            buttons = ttk.Frame(frame)
            buttons.pack(fill='x', pady=5)
            ttk.Button(buttons, text='Punkt hinzufügen', command=lambda f=field: self.edit_point(f, True)).pack(side='left')
            ttk.Button(buttons, text='Punkt ändern', command=lambda f=field: self.edit_point(f, False)).pack(side='left', padx=6)
            ttk.Button(buttons, text='Punkt löschen', command=lambda f=field: self.delete_point(f)).pack(side='left')
            tree.bind('<Double-1>', lambda event, f=field: self.edit_point(f, False))
        self.plot = plot_class(self.window, height=260)
        self.plot.pack(fill='both', expand=True, padx=12, pady=8)
        buttons = ttk.Frame(self.window, padding=12)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Prüfen / Vorschau', command=self.preview).pack(side='left')
        ttk.Button(buttons, text='INI speichern …', command=self.save).pack(side='left', padx=8)
        ttk.Button(buttons, text='Schließen ohne Speichern', command=self.close).pack(side='right')
        self.initial_values = self.values()
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.preview()

    def close(self):
        if self.values() != self.initial_values:
            if not messagebox.askyesno('Änderungen verwerfen', 'Ungespeicherte Änderungen verwerfen?', parent=self.window):
                return
        self.window.destroy()

    def values(self):
        result = {self.prefix+field: variable.get().strip() for field, variable in self.fields.items()}
        if self.kind == 'profiles':
            result[self.prefix+'Enabled'] = '1' if self.enabled.get() else '0'
            result[self.prefix+'WaitForTemperatureEnable'] = '1' if self.wait.get() else '0'
        for field, tree in self.curves.items():
            rows = [tree.item(item, 'values') for item in tree.get_children()]
            result[self.prefix+field+'Points'] = str(len(rows))
            for index, (stamp, value) in enumerate(rows, 1):
                result[self.prefix+f'{field}{index:02}_Time'] = str(stamp)
                result[self.prefix+f'{field}{index:02}_Set'] = str(value)
        return result

    def edit_point(self, field, add):
        tree = self.curves[field]
        selected = tree.selection()
        if add and len(tree.get_children()) >= 32:
            messagebox.showwarning('Stützpunkte', 'Maximal 32 Stützpunkte je Kurve.', parent=self.window); return
        if not add and not selected:
            messagebox.showinfo('Stützpunkte', 'Zuerst einen Punkt auswählen.', parent=self.window); return
        old = ('0', '0') if add else tree.item(selected[0], 'values')
        stamp = simpledialog.askinteger('Punkt', 'Zeit [s], ganze Zahl:', initialvalue=int(old[0]), minvalue=0, parent=self.window)
        if stamp is None: return
        value = simpledialog.askfloat('Punkt', 'Sollwert (Operation: 0/1, Feuchte/Lift: 0..100):', initialvalue=float(old[1]), parent=self.window)
        if value is None: return
        if add: tree.insert('', 'end', values=(stamp, value))
        else: tree.item(selected[0], values=(stamp, value))
        ordered = sorted(tree.get_children(), key=lambda item: int(tree.item(item, 'values')[0]))
        for index, item in enumerate(ordered): tree.move(item, '', index)
        self.preview()

    def delete_point(self, field):
        tree = self.curves[field]
        if len(tree.get_children()) <= 1:
            messagebox.showwarning('Stützpunkte', 'Mindestens ein Stützpunkt muss bleiben.', parent=self.window); return
        if tree.selection():
            tree.delete(*tree.selection())
            self.preview()

    def preview(self):
        try:
            values = self.values()
            replace_section(self.original.decode('utf-8-sig'), self.section, values, self.kind)
            curves = []
            for field, label, stepped, color in self.specs:
                points = [{'Time_s': int(values[self.prefix+f'{field}{i:02}_Time']),
                           'Value': float(values[self.prefix+f'{field}{i:02}_Set'])}
                          for i in range(1, int(values[self.prefix+field+'Points'])+1)]
                curves.append((label, points, stepped, color))
            self.plot.show(values[self.prefix+'Name'], int(values[self.prefix+'Duration']), curves,
                           self.enabled.get() if self.kind == 'profiles' else True)
            return True
        except Exception as exc:
            self.plot.clear()
            messagebox.showerror('Eingaben prüfen', str(exc), parent=self.window)
            return False

    def save(self):
        if not self.preview(): return
        if not messagebox.askyesno('INI speichern', 'Lokale INI speichern und Sicherung anlegen?\n'+str(self.path)+
                                   '\nKeine PLC-Übernahme. INI-Kommentare werden beim Speichern entfernt.', parent=self.window): return
        try:
            backup = save_section(self.path, self.original, self.section, self.values(), self.kind)
            self.app.log('INI gespeichert; Sicherung: '+str(backup))
            self.app.read(self.kind)
            self.window.destroy()
        except Exception as exc:
            messagebox.showerror('Speichern fehlgeschlagen', str(exc), parent=self.window)
