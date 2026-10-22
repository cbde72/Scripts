"""Local catalog editor; IDs/sections remain stable; no ADS side effects."""
import configparser
from datetime import datetime
import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import messagebox, ttk
import uuid
from device_catalog_dry_run import validate_text


def edit_entry(original, section, changes):
    text = original.decode('utf-8-sig')
    validate_text(text)
    if not re.fullmatch(r'(DUT|ECU)_\d{3}', section):
        raise ValueError('Nur vorhandene DUT-/ECU-Eintraege bearbeiten')
    if set(changes) != {'Name', 'Serial', 'Type', 'Info', 'Enabled'}:
        raise ValueError('Felder unvollstaendig oder nicht erlaubt')
    match = re.search(r'(?m)^\['+re.escape(section)+r'\][^\r\n]*(?:\r?\n|$)', text)
    if not match:
        raise ValueError('Abschnitt fehlt')
    end = re.search(r'(?m)^\[', text[match.end():])
    end = match.end()+end.start() if end else len(text)
    block = text[match.end():end]
    for key, value in changes.items():
        if '\n' in value or '\r' in value:
            raise ValueError('Zeilenumbrueche sind nicht erlaubt')
        pattern = r'(?m)^('+key+r'\s*=)[^\r\n]*'
        block, count = re.subn(pattern, lambda m: m[1]+value, block)
        if count != 1:
            raise ValueError('Feld fehlt oder doppelt: '+key)
    result = text[:match.end()]+block+text[end:]
    validate_text(result)
    # Reject ambiguous active serials in the same device class.
    parsed = validate_text(result)
    for kind in ['DUT', 'ECU']:
        serials = [e['Serial'] for e in parsed[kind] if e['Enabled']]
        if len(serials) != len(set(serials)):
            raise ValueError('Doppelte aktive Seriennummer: '+kind)
    return result.encode('utf-8')


def save_entry(path, original, section, changes):
    path = Path(path)
    result = edit_entry(original, section, changes)
    if path.read_bytes() != original:
        raise ValueError('Datei extern geaendert; erneut einlesen')
    backup = path.with_name(path.name+'.'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.bak')
    with backup.open('xb') as f:
        f.write(original)
        f.flush(); os.fsync(f.fileno())
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as f:
            f.write(result); f.flush(); os.fsync(f.fileno())
        if path.read_bytes() != original:
            raise ValueError('Datei inzwischen extern geaendert')
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup


class CatalogEditor:
    def __init__(self, app):
        if app.store.candidate or getattr(app, 'online_candidate', None):
            raise ValueError('Erst offenen Transfer klaeren')
        self.app = app
        self.path = Path(app.paths['catalog'].get())
        self.original = self.path.read_bytes()
        parsed = validate_text(self.original.decode('utf-8-sig'))
        self.window = tk.Toplevel(app.root)
        self.window.title('DeviceCatalog lokal bearbeiten')
        self.window.geometry('900x630')
        self.window.transient(app.root); self.window.grab_set()
        ttk.Label(self.window, text=str(self.path), wraplength=850).pack(padx=12, pady=8)
        ttk.Label(self.window, text='IDs bleiben unveraendert. Speichern aendert nur die lokale INI; PLC-Uebernahme separat.').pack()
        self.tree = ttk.Treeview(self.window, columns=('id', 'name', 'serial', 'enabled'), show='headings', height=12)
        for key in ['id', 'name', 'serial', 'enabled']:
            self.tree.heading(key, text=key)
        for kind in ['DUT', 'ECU']:
            for entry in parsed[kind]:
                self.tree.insert('', 'end', iid=entry['Key'], values=(entry['Key'],entry['Name'],entry['Serial'],int(entry['Enabled'])))
        self.tree.pack(fill='both', expand=True, padx=12, pady=10)
        self.fields = {}
        form = ttk.Frame(self.window); form.pack(fill='x', padx=12)
        for index, name in enumerate(['Name', 'Serial', 'Type', 'Info', 'Enabled']):
            ttk.Label(form, text=name).grid(row=index, column=0, sticky='w')
            value = tk.StringVar(); self.fields[name] = value
            ttk.Entry(form, textvariable=value, width=80).grid(row=index, column=1, sticky='ew', pady=2)
        ttk.Button(self.window, text='Eintrag lokal speichern ...', command=self.save).pack(pady=10)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        first = self.tree.get_children()[0]; self.tree.selection_set(first); self.select()

    def select(self, event=None):
        chosen = self.tree.selection()
        if not chosen:
            return
        parser = configparser.ConfigParser(interpolation=None); parser.optionxform = str
        parser.read_string(self.original.decode('utf-8-sig'))
        for key, variable in self.fields.items():
            variable.set(parser[chosen[0]][key])

    def save(self):
        try:
            chosen = self.tree.selection()[0]
            changes = {k:v.get() for k,v in self.fields.items()}
            edit_entry(self.original, chosen, changes)
            if not messagebox.askyesno('Lokales Speichern', f'{chosen} in dieser INI speichern?\nEine bytegenaue Sicherung wird angelegt.\nKeine PLC-Uebernahme.', parent=self.window):
                return
            backup = save_entry(self.path, self.original, chosen, changes)
            self.app.log('Katalog lokal gespeichert; Sicherung: '+str(backup))
            self.app.read('catalog')
            self.window.destroy()
        except (OSError, ValueError, IndexError) as exc:
            messagebox.showerror('Nicht gespeichert', str(exc), parent=self.window)
