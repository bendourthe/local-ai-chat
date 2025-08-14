"""
Tkinter GUI for Foundry Local Desktop Chat.

Provides model installation, model listing, interactive chat, and chat persistence sidebar with a modern dark theme.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import os
import sys
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable
import re
import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap import ttk
from tkinter import messagebox, simpledialog
from core.foundry_cli import FoundryCLI
from core import storage

_APP_TITLE = 'Local AI Chat'

# Colors per spec (Slack/Teams dark-like)
_CHAT_BG = '#1E1E1E'
_SIDE_BG = '#252526'
_INPUT_BG = '#2A2A2C'
_FG = '#FFFFFF'
_META = '#AAAAAA'  # timestamp
_PLACEHOLDER = '#999999'
_USER_TXT = '#FFFFFF'
_ASSIST_TXT = '#E5E5E7'
_USER_BG = '#0A84FF'
_ASSIST_BG = '#2C2C2E'
_ACCENT = '#0A84FF'
_BUBBLE_OUTLINE = '#111111'
_BUBBLE_RAD = 12
_PAD_X = 12
_PAD_Y = 8
_GAP_Y = 12
_SHADOW = '#151515'

# Window background equals chat background
_BG = _CHAT_BG

# Fonts with pixel-accurate sizes using negative values
_FONT_FAMILY = 'Segoe UI'
_FONT_CHAT = (_FONT_FAMILY, -14)
_FONT_TS = (_FONT_FAMILY, -12)
_FONT_SENDER = (_FONT_FAMILY, -13, 'bold')

def _asset_candidates(name: str) -> List[str]:
    """Return candidate asset paths for dev and bundled runs."""
    here = os.path.dirname(__file__)
    base_dev = os.path.join(here, 'assets')
    paths = [os.path.join(base_dev, name)]
    try:
        if getattr(sys, 'frozen', False):
            # PyInstaller onefile extracts data under _MEIPASS
            base = getattr(sys, '_MEIPASS', None)
            if base:
                paths.insert(0, os.path.join(base, 'src', 'gui', 'assets', name))
                paths.insert(1, os.path.join(base, 'assets', name))
            # Fallback: a side-by-side unpacked 'src' directory near the executable
            exe_dir = os.path.dirname(sys.executable)
            paths.insert(2, os.path.join(exe_dir, 'src', 'gui', 'assets', name))
            paths.insert(3, os.path.join(exe_dir, 'assets', name))
    except Exception:
        pass
    return paths

def _rounded_rect(c: tk.Canvas, x1: int, y1: int, x2: int, y2: int, r: int, fill: str, outline: str = '', width: int = 0) -> None:
    """Draw a rounded rectangle on a Canvas."""
    if r <= 0:
        c.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width)
        return
    c.create_arc(x1, y1, x1 + 2*r, y1 + 2*r, start=90, extent=90, style='pieslice', outline=outline, width=width, fill=fill)
    c.create_arc(x2 - 2*r, y1, x2, y1 + 2*r, start=0, extent=90, style='pieslice', outline=outline, width=width, fill=fill)
    c.create_arc(x2 - 2*r, y2 - 2*r, x2, y2, start=270, extent=90, style='pieslice', outline=outline, width=width, fill=fill)
    c.create_arc(x1, y2 - 2*r, x1 + 2*r, y2, start=180, extent=90, style='pieslice', outline=outline, width=width, fill=fill)
    c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=outline, width=width)
    c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=outline, width=width)

class ChatView(ttk.Frame):
    """Scrollable canvas with rounded message bubbles and avatars."""
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(self, bg=_BG, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vsb.grid(row=0, column=1, sticky='ns')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._y = 12
        self.bind('<Configure>', self._on_resize)
        self.canvas.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Enter>', self._bind_mousewheel)
        self.canvas.bind('<Leave>', self._unbind_mousewheel)
    def _on_resize(self, _evt: Optional[object] = None) -> None:
        """Update scrollregion when the widget resizes."""
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
    def clear(self) -> None:
        """Remove all drawn items."""
        self.canvas.delete('all')
        self._y = 12
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
    def add(self, role: str, text: str, ts: Optional[str] = None) -> None:
        """Add a message bubble for role in {'user','assistant'} with optional timestamp."""
        max_w = max(420, int(self.winfo_width() * 0.6))
        avatar_r = 14
        is_user = (role == 'user')
        bx = 64
        # Extract timestamp prefix if embedded
        if not ts:
            m = re.match(r'^(\d{2}:\d{2})\s\s', text)
            if m:
                ts = m.group(1)
                text = text[len(m.group(0)):] or text
        tx = bx if not is_user else max(500, int(self.winfo_width() * 0.94)) - max_w
        ty = self._y
        tw = max_w - (avatar_r*2 + 12 if not is_user else 6)
        # Role label (bold small caps)
        role_lbl = 'YOU' if is_user else 'AI'
        lbl_x = tx + _PAD_X if not is_user else tx + max_w - _PAD_X - 30
        self.canvas.create_text(lbl_x, ty - 16, text=role_lbl, fill=_META, anchor='nw', font=_FONT_SENDER)
        # Message text and bubble
        text_id = self.canvas.create_text(tx + _PAD_X, ty + _PAD_Y, text=text, fill=_USER_TXT if is_user else _ASSIST_TXT, anchor='nw', font=_FONT_CHAT, width=tw)
        bbox = self.canvas.bbox(text_id) or (tx, ty, tx + 120, ty + 40)
        x1, y1, x2, y2 = bbox
        x1 -= _PAD_X
        y1 -= _PAD_Y
        x2 += _PAD_X
        y2 += _PAD_Y
        # Shadow
        _rounded_rect(self.canvas, x1 + 1, y1 + 1, x2 + 1, y2 + 1, _BUBBLE_RAD, fill=_SHADOW, outline='', width=0)
        # Bubble
        _rounded_rect(self.canvas, x1, y1, x2, y2, _BUBBLE_RAD, fill=_USER_BG if is_user else _ASSIST_BG, outline=_BUBBLE_OUTLINE, width=1)
        self.canvas.tag_raise(text_id)
        # Timestamp
        if ts:
            if is_user:
                self.canvas.create_text(x2 - _PAD_X, y2 + 2, text=ts, fill=_META, anchor='ne', font=_FONT_TS)
            else:
                self.canvas.create_text(x1 + _PAD_X, y2 + 2, text=ts, fill=_META, anchor='nw', font=_FONT_TS)
        # Avatar
        av_y1 = y2 - avatar_r*2 if is_user else y1
        av_y2 = av_y1 + avatar_r*2
        if is_user:
            av_x1 = x2 + 6
            av_x2 = av_x1 + avatar_r*2
        else:
            av_x1 = x1 - 6 - avatar_r*2
            av_x2 = av_x1 + avatar_r*2
        self.canvas.create_oval(av_x1, av_y1, av_x2, av_y2, fill=_ACCENT if is_user else '#2d3646', outline='')
        self.canvas.create_text((av_x1+av_x2)//2, (av_y1+av_y2)//2, text='U' if is_user else 'A', fill='#ffffff', font=('Segoe UI', 9, 'bold'))
        self._y = y2 + _GAP_Y + 10
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.canvas.yview_moveto(1.0)
    def _bind_mousewheel(self, _evt: Optional[object] = None) -> None:
        """Bind mouse wheel to canvas for smooth scrolling."""
        def _on_wheel(e: tk.Event) -> None:
            delta = 0
            try:
                delta = int(e.delta/120)
            except Exception:
                delta = 0
            self.canvas.yview_scroll(-delta, 'units')
        self._wheelid = self.canvas.bind_all('<MouseWheel>', _on_wheel)
    def _unbind_mousewheel(self, _evt: Optional[object] = None) -> None:
        """Unbind mouse wheel when cursor leaves the canvas."""
        try:
            self.canvas.unbind_all('<MouseWheel>')
        except Exception:
            pass

class App(tb.Window):
    """Main application window and controllers."""
    def __init__(self) -> None:
        """Initialize widgets and state."""
        super().__init__(themename='darkly')
        self.title(_APP_TITLE)
        for p in _asset_candidates('logo.ico'):
            try:
                if os.path.exists(p):
                    self.iconbitmap(p)
                    break
            except Exception:
                pass
        for p in _asset_candidates('logo.png'):
            try:
                if os.path.exists(p):
                    self._icon_img = tk.PhotoImage(file=p)
                    self.iconphoto(True, self._icon_img)
                    break
            except Exception:
                pass
        self.geometry('1100x700')
        self.minsize(980, 600)
        self.configure(bg=_BG)
        self.style.configure('.', font=(_FONT_FAMILY, -13))
        self.style.configure('TFrame', background=_BG)
        self.style.configure('TLabel', foreground=_FG, background=_BG)
        # Side frame style
        self.style.configure('Side.TFrame', background=_SIDE_BG)
        # Button styles
        self.style.configure('Primary.TButton', background=_ACCENT, foreground='#FFFFFF', padding=6, relief='flat', borderwidth=0)
        self.style.map('Primary.TButton', background=[('active', '#2B95FF')])
        self.style.configure('Danger.TButton', background='#FF3B30', foreground='#FFFFFF', padding=6, relief='flat', borderwidth=0)
        self.style.map('Danger.TButton', background=[('active', '#FF584E')])
        self.style.configure('Secondary.TButton', background='#444444', foreground='#FFFFFF', padding=6, relief='flat', borderwidth=0)
        self.style.map('Secondary.TButton', background=[('active', '#555555')])
        self._cli = FoundryCLI()
        self._current_chat_id: Optional[str] = None
        self._messages: List[Dict] = []
        self._streaming_lock = threading.Lock()
        self._pending_prompt: Optional[str] = None
        self._build_ui()
        self.after(100, self._post_init)
        self.bind_all('<Control-n>', lambda e: self._new_chat())
        self.bind_all('<F2>', lambda e: self._rename_chat())
        self.bind_all('<Delete>', lambda e: self._delete_chat())
        self.bind_all('<Control-k>', lambda e: self.input_entry.focus_set())
        self.bind_all('<Control-l>', lambda e: self.model_combo.focus_set())
    def _post_init(self) -> None:
        """Deferred init to check install, onboard downloads, then load chats."""
        def after_install() -> None:
            def on_models(models: List[str]) -> None:
                avail = list(models)
                # Only prompt for downloads at startup if nothing is downloaded yet
                dls_existing = storage.get_downloaded_models()
                if not dls_existing and avail:
                    picked = self._prompt_model_downloads(avail)
                    if picked:
                        self._download_models(picked)
                        dls_existing = storage.get_downloaded_models()
                if dls_existing:
                    self.model_var.set(dls_existing[0])
                self._apply_models(avail)
                # Purge empty chats from history and load remaining without auto-creating a new chat
                try:
                    for item in list(storage.list_chats()):
                        data = storage.load_chat(item['id'])
                        if not data or not data.get('messages'):
                            storage.delete_chat(item['id'])
                except Exception:
                    pass
                self._refresh_chats()
            self._refresh_models(on_done=on_models)
        if not self._cli.is_installed():
            if messagebox.askyesno('Foundry Local', 'Foundry Local is not installed. Install now with Admin privileges via winget?'):
                def run_install() -> None:
                    self._set_status('Installing Foundry (Admin)...')
                    def on_out(line: str) -> None:
                        self._set_status(line)
                    code = self._cli.install_foundry(on_out, elevated=True)
                    self.after(0, lambda: self._set_status('Install successful' if code == 0 else f'Install failed ({code})'))
                    if code == 0:
                        self.after(300, after_install)
                    else:
                        self.after(0, lambda: messagebox.showerror('Install Failed', 'Installation failed. Please retry from an elevated PowerShell: winget source update; winget install --id Microsoft.FoundryLocal --accept-package-agreements --accept-source-agreements'))
                threading.Thread(target=run_install, daemon=True).start()
            else:
                self._set_status('Foundry not installed')
        else:
            after_install()
    def _build_ui(self) -> None:
        """Create layout and widgets."""
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(self, padding=0, style='Side.TFrame')
        sidebar.grid(row=0, column=0, sticky='nsw')
        sidebar.rowconfigure(1, weight=1)
        ttk.Label(sidebar, text='Chats', font=(_FONT_FAMILY, -13, 'bold'), foreground=_FG, background=_SIDE_BG).grid(row=0, column=0, padx=10, pady=(10, 4), sticky='w')
        self.chat_list = tk.Listbox(sidebar, height=20, bg=_SIDE_BG, fg=_FG, highlightthickness=0, selectbackground=_ACCENT, selectforeground='#FFFFFF', relief='flat', activestyle='none')
        self.chat_list.grid(row=1, column=0, padx=10, pady=0, sticky='nsw')
        self.chat_list.bind('<<ListboxSelect>>', self._on_select_chat)
        btns = ttk.Frame(sidebar)
        btns.grid(row=2, column=0, padx=10, pady=8, sticky='ew')
        ttk.Button(btns, text='➕ New', style='Secondary.TButton', command=self._new_chat).grid(row=0, column=0, padx=2)
        ttk.Button(btns, text='✎ Rename', style='Secondary.TButton', command=self._rename_chat).grid(row=0, column=1, padx=2)
        ttk.Button(btns, text='🗑 Delete', style='Danger.TButton', command=self._delete_chat).grid(row=0, column=2, padx=2)
        main = ttk.Frame(self, padding=0)
        main.grid(row=0, column=1, sticky='nsew')
        main.rowconfigure(2, weight=1)
        main.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(main)
        toolbar.grid(row=0, column=0, sticky='ew', padx=8, pady=8)
        self._toolbar_logo = None
        for p in _asset_candidates('logo.png'):
            try:
                if os.path.exists(p):
                    _img = tk.PhotoImage(file=p)
                    _w, _h = _img.width(), _img.height()
                    _f = 1
                    while _w//_f > 20 or _h//_f > 20:
                        _f += 1
                    if _f > 1:
                        _img = _img.subsample(_f, _f)
                    self._toolbar_logo = _img
                    break
            except Exception:
                pass
        if self._toolbar_logo:
            ttk.Label(toolbar, image=self._toolbar_logo, text=' Local AI Chat', compound='left', font=('Segoe UI', 11, 'bold')).grid(row=0, column=0, padx=(0,10))
        ttk.Label(toolbar, text='Model:', foreground=_META).grid(row=0, column=1, padx=(0,4))
        self.model_var = tk.StringVar(value='')
        self.model_combo = ttk.Combobox(toolbar, textvariable=self.model_var, values=[], width=44, state='readonly')
        self.model_combo.grid(row=0, column=2, padx=4)
        self.model_combo.bind('<<ComboboxSelected>>', self._on_model_changed)
        ttk.Button(toolbar, text='⟳ Refresh', style='Secondary.TButton', command=self._refresh_models).grid(row=0, column=3, padx=4)
        ttk.Button(toolbar, text='🗑 Delete Model', style='Danger.TButton', command=self._delete_selected_model).grid(row=0, column=4, padx=4)
        self.status_var = tk.StringVar(value='Ready')
        self.status_lbl = ttk.Label(toolbar, textvariable=self.status_var, bootstyle='secondary')
        self.status_lbl.grid(row=0, column=5, padx=12)
        ttk.Separator(main, orient='horizontal').grid(row=1, column=0, sticky='ew', padx=8)
        chat_frame = ttk.Frame(main)
        chat_frame.grid(row=2, column=0, sticky='nsew', padx=8, pady=6)
        chat_frame.rowconfigure(0, weight=1)
        chat_frame.columnconfigure(0, weight=1)
        self.chat_view = ChatView(chat_frame)
        self.chat_view.grid(row=0, column=0, sticky='nsew')
        input_frame = ttk.Frame(main)
        input_frame.grid(row=3, column=0, sticky='ew', padx=8, pady=8)
        input_frame.columnconfigure(0, weight=1)
        # Canvas wrapper to simulate rounded input bar with inner shadow
        self.input_var = tk.StringVar(value='')
        entry_wrap = tk.Canvas(input_frame, bg=_BG, highlightthickness=0, height=40)
        entry_wrap.grid(row=0, column=0, sticky='ew', padx=(0,8))
        input_frame.bind('<Configure>', lambda e: entry_wrap.configure(width=e.width - 100))
        # Draw the rounded background and place the Entry inside
        def _redraw_input() -> None:
            entry_wrap.delete('all')
            w = max(200, entry_wrap.winfo_width())
            h = 36
            x1, y1, x2, y2 = 2, 2, w - 2, h
            _rounded_rect(entry_wrap, x1, y1, x2, y2, 10, fill=_INPUT_BG, outline='#1f1f20', width=1)
            # inner shadow lines (subtle)
            entry_wrap.create_line(x1 + 10, y1 + 1, x2 - 10, y1 + 1, fill='#1b1b1c')
            entry_wrap.create_line(x1 + 10, y2 - 2, x2 - 10, y2 - 2, fill='#171718')
            # Place Entry
            if not hasattr(self, 'input_entry'):
                self.input_entry = ttk.Entry(entry_wrap, textvariable=self.input_var)
                self.input_entry.configure(width=10)
                self.input_entry.bind('<Return>', lambda e: self._send())
            entry_wrap.create_window(x1 + 12, y1 + 6, anchor='nw', window=self.input_entry, width=w - 140, height=24)
            # Placeholder
            if not hasattr(self, '_ph_label'):
                self._ph_label = ttk.Label(entry_wrap, text='Type a message…', foreground=_PLACEHOLDER, background='')
            txt = self.input_var.get().strip()
            try:
                if txt:
                    self._ph_label.place_forget()
                else:
                    self._ph_label.place(in_=entry_wrap, x=x1 + 18, y=y1 + 8)
            except Exception:
                pass
        entry_wrap.bind('<Configure>', lambda e: _redraw_input())
        if entry_wrap.winfo_ismapped():
            _redraw_input()
        self.input_var.trace_add('write', lambda *_: _redraw_input())
        # Send button
        self.send_btn = ttk.Button(input_frame, text='Send', style='Primary.TButton', command=self._send)
        self.send_btn.grid(row=0, column=1)
        # ChatView handles styling
    def _refresh_models(self, on_done: Optional[Callable[[List[str]], None]] = None) -> None:
        """Refresh model list from CLI."""
        def run() -> None:
            self._set_status('Loading models...')
            # Get available models and migrate any legacy alias entries to model IDs
            models = self._cli.list_models()
            try:
                pairs = self._cli.list_cached_pairs()
                storage.migrate_downloaded_aliases(pairs)
            except Exception:
                pass
            self._all_models = models
            self.after(0, lambda: self._apply_models(models))
            if on_done:
                self.after(0, lambda: on_done(models))
            self.after(0, lambda: self._set_status('Ready'))
        threading.Thread(target=run, daemon=True).start()
    def _apply_models(self, models: List[str]) -> None:
        """Populate model combobox with downloaded models first, then available section."""
        downloaded = set(storage.get_downloaded_models())
        d = [m for m in models if m in downloaded]
        a = [m for m in models if m not in downloaded]
        sep = '──────── Available ────────'
        vals = d + ([sep] if a else []) + a
        self._combo_sep = sep
        self._combo_all_models = set(models)
        self.model_combo.configure(values=vals)
        if d and (self.model_var.get() not in d):
            self.model_var.set(d[0])
        self._set_status('Ready')

    def _delete_selected_model(self) -> None:
        """Delete the currently selected model from local cache and registry."""
        model = self.model_var.get().strip()
        if not model or model == getattr(self, '_combo_sep', ''):
            messagebox.showwarning('Delete Model', 'Select a model to delete.')
            return
        if not messagebox.askyesno('Delete Model', f'Remove cached model "{model}" from disk?'):
            return
        self._set_status(f'Deleting {model}...')
        def worker() -> None:
            ok = False
            try:
                ok = self._cli.remove_cached_model(model)
            except Exception:
                ok = False
            def done() -> None:
                if ok:
                    # Remove both the id and any alias pointing to it from registry
                    pairs = {}
                    try:
                        pairs = {a: mid for a, mid in self._cli.list_cached_pairs()}
                    except Exception:
                        pairs = {}
                    storage.remove_downloaded_model(model)
                    # If user selected an alias and its id is different, remove alias entry too; vice-versa
                    for alias, mid in pairs.items():
                        if model == mid:
                            storage.remove_downloaded_model(alias)
                        if model == alias:
                            storage.remove_downloaded_model(mid)
                    self._apply_models(list(getattr(self, '_all_models', [])))
                    if model == self.model_var.get():
                        self.model_var.set('')
                    self._set_status('Model deleted')
                else:
                    self._set_status('Delete failed')
            self.after(0, done)
        threading.Thread(target=worker, daemon=True).start()
    def _print_message(self, role: str, content: str, ts_iso: Optional[str] = None) -> None:
        """Render a message bubble in the transcript, preserving timestamp if provided."""
        ts_str = datetime.now().strftime('%H:%M')
        if ts_iso:
            try:
                ts_str = datetime.fromisoformat(ts_iso).strftime('%H:%M')
            except Exception:
                ts_str = ts_str
        self.chat_view.add(role, content, ts_str)
    def _append_chat(self, role: str, content: str) -> None:
        """Append a message to the chat text box and persist."""
        now_iso = datetime.now().isoformat()
        self._print_message(role, content, now_iso)
        self._messages.append({'role': role, 'content': content, 'ts': now_iso})
        if self._current_chat_id:
            storage.save_messages(self._current_chat_id, self._messages)
    def _new_chat(self, initial: bool = False) -> None:
        """Create a new chat and focus input."""
        title = 'New Chat' if initial else (simpledialog.askstring('New Chat', 'Title:') or 'New Chat')
        chat_id = storage.create_chat(title)
        self._current_chat_id = chat_id
        self._messages = []
        self._refresh_chats(select_id=chat_id)
        self._clear_transcript()
        self.input_entry.focus_set()
    def _rename_chat(self) -> None:
        """Rename selected chat."""
        idx = self._selected_index()
        if idx is None:
            return
        item = self._chat_items[idx]
        new_title = simpledialog.askstring('Rename Chat', 'New title:', initialvalue=item['title'])
        if not new_title:
            return
        storage.rename_chat(item['id'], new_title)
        self._refresh_chats(select_id=item['id'])
    def _delete_chat(self) -> None:
        """Delete selected chat and clear view."""
        idx = self._selected_index()
        if idx is None:
            return
        item = self._chat_items[idx]
        if messagebox.askyesno('Delete Chat', f'Delete "{item["title"]}"? This cannot be undone.'):
            storage.delete_chat(item['id'])
            self._refresh_chats()
            self._current_chat_id = None
            self._messages = []
            self._clear_transcript()
    def _on_select_chat(self, _event: object) -> None:
        """Load selected chat into the transcript."""
        idx = self._selected_index()
        if idx is None:
            return
        item = self._chat_items[idx]
        data = storage.load_chat(item['id'])
        if not data:
            return
        self._current_chat_id = item['id']
        self._messages = data.get('messages', [])
        self._render_messages()
    def _selected_index(self) -> Optional[int]:
        """Return selected listbox index or None."""
        sel = self.chat_list.curselection()
        if not sel:
            return None
        return int(sel[0])
    def _refresh_chats(self, select_id: Optional[str] = None) -> None:
        """Reload chat list from storage."""
        self._chat_items = storage.list_chats()
        self.chat_list.delete(0, 'end')
        for item in self._chat_items:
            self.chat_list.insert('end', item['title'])
        if select_id:
            for i, item in enumerate(self._chat_items):
                if item['id'] == select_id:
                    self.chat_list.selection_clear(0, 'end')
                    self.chat_list.selection_set(i)
                    self.chat_list.activate(i)
                    self.chat_list.see(i)
                    break
    def _render_messages(self) -> None:
        """Render in-memory messages to the transcript widget."""
        self._clear_transcript()
        for m in self._messages:
            self._print_message(m.get('role', 'assistant'), m.get('content', ''), m.get('ts'))
    def _clear_transcript(self) -> None:
        """Empty the transcript text widget."""
        self.chat_view.clear()
    def _send(self) -> None:
        """Send prompt to the running session, starting one if needed."""
        text = self.input_var.get().strip()
        if not text:
            return
        model = self.model_var.get().strip()
        if not model or model == getattr(self, '_combo_sep', ''):
            messagebox.showwarning('Model', 'Select a model first.')
            return
        if model not in getattr(self, '_combo_all_models', set()):
            messagebox.showwarning('Model', 'Select a valid model.')
            return
        if model not in set(storage.get_downloaded_models()):
            if messagebox.askyesno('Download model', f'"{model}" is not downloaded. Download now?'):
                self._download_models([model])
                self._apply_models(list(self._all_models))
                self.model_var.set(model)
            else:
                return
        self.input_var.set('')
        # Auto-create a chat on first send if none exists
        if not getattr(self, '_current_chat_id', None):
            chat_id = storage.create_chat('New Chat')
            self._current_chat_id = chat_id
            self._messages = []
            self._refresh_chats(select_id=chat_id)
            self._clear_transcript()
        self._append_chat('user', text)
        if not self._is_session_active():
            self._pending_prompt = text
            self._start_session(model)
        else:
            self._cli.send_prompt(text)
    def _is_session_active(self) -> bool:
        """Return True if CLI background session is alive."""
        return hasattr(self._cli, '_proc') and self._cli._proc is not None and self._cli._proc.poll() is None
    def _start_session(self, model: str) -> None:
        """Start background CLI session and wire callbacks."""
        self._set_status(f'Starting {model}...')
        def on_raw(line: str) -> None:
            if 'Interactive mode' in line or 'Interactive Chat' in line or 'Enter /?' in line:
                self._set_status(line)
                if self._pending_prompt:
                    self._cli.send_prompt(self._pending_prompt)
                    self._pending_prompt = None
        def on_assistant(text: str) -> None:
            self.after(0, lambda: self._append_chat('assistant', text.strip()))
            self.after(0, lambda: self._set_status('Ready'))
        self._cli.start_chat(model, on_raw_output=on_raw, on_assistant=on_assistant)
    def _on_model_changed(self, _evt: object) -> None:
        """Handle combobox selection; trigger download if needed."""
        val = self.model_var.get().strip()
        if not val or val == getattr(self, '_combo_sep', ''):
            return
        if val not in getattr(self, '_combo_all_models', set()):
            return
        if val not in set(storage.get_downloaded_models()):
            if messagebox.askyesno('Download model', f'"{val}" is not downloaded. Download now?'):
                self._download_models([val])
                self._apply_models(list(self._all_models))
                self.model_var.set(val)
    def _set_status(self, text: str) -> None:
        """Update status label thread-safely."""
        try:
            # If we're on the main thread, update directly; otherwise, marshal to UI thread.
            import threading
            if threading.current_thread() is threading.main_thread():
                self.status_var.set(text)
            else:
                self.after(0, lambda: self.status_var.set(text))
        except Exception:
            # Best-effort safety: ignore errors from shutdown races
            pass

    def _prompt_model_downloads(self, models: List[str]) -> List[str]:
        """Show a modal multi-select list of models to download; return chosen list."""
        sel: List[str] = []
        win = tk.Toplevel(self)
        win.title('Download models')
        win.transient(self)
        win.grab_set()
        ttk.Label(win, text='Select models to download', font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, padx=12, pady=(12,6), sticky='w')
        lb = tk.Listbox(win, selectmode='multiple', width=48, height=12, bg=_PANEL, fg=_FG, highlightthickness=0, selectbackground='#2b3a55', selectforeground=_FG, relief='flat')
        for m in models:
            lb.insert('end', m)
        lb.grid(row=1, column=0, padx=12, pady=6, sticky='nsew')
        btns = ttk.Frame(win)
        btns.grid(row=2, column=0, padx=12, pady=(6,12), sticky='e')
        def do_ok() -> None:
            nonlocal sel
            sel = [lb.get(i) for i in lb.curselection()]
            win.destroy()
        def do_skip() -> None:
            sel.clear()
            win.destroy()
        ttk.Button(btns, text='Download', bootstyle='success', command=do_ok).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text='Skip', bootstyle='secondary', command=do_skip).grid(row=0, column=1, padx=4)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        self.wait_window(win)
        return sel

    def _download_models(self, models: List[str]) -> None:
        """Sequentially download models with a simple progress dialog."""
        if not models:
            return
        dlg = tk.Toplevel(self)
        dlg.title('Downloading models')
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(dlg, text='Downloading models...', font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, padx=12, pady=(12,6), sticky='w')
        status_var = tk.StringVar(value='')
        lbl = ttk.Label(dlg, textvariable=status_var, anchor='w', wraplength=520, justify='left')
        lbl.grid(row=1, column=0, padx=12, pady=6, sticky='nsew')
        pb = ttk.Progressbar(dlg, mode='indeterminate', bootstyle='info-striped')
        pb.grid(row=2, column=0, padx=12, pady=(6,12), sticky='ew')
        dlg.columnconfigure(0, weight=1)
        dlg.rowconfigure(1, weight=1)
        pb.start(12)
        def append(txt: str) -> None:
            # Collapse noisy bar characters
            clean = txt.replace('#', '').replace('[', '').replace(']', '').strip()
            status_var.set(clean)
        def worker() -> None:
            ok_any = False
            for m in models:
                append(f'Fetching {m}...')
                def on_out(line: str) -> None:
                    self.after(0, lambda: append(line))
                ok = self._cli.ensure_model_downloaded(m, on_out)
                if ok:
                    storage.add_downloaded_model(m)
                    ok_any = True
                    self.after(0, lambda: append(f'{m} ready.'))
                else:
                    self.after(0, lambda: append(f'Failed to fetch {m}.'))
            self.after(0, pb.stop)
            self.after(0, dlg.destroy)
            if ok_any:
                def _after_dl() -> None:
                    self._set_status('Models downloaded')
                    # Re-apply grouping using the latest downloaded registry
                    self._apply_models(list(getattr(self, '_all_models', [])))
                    # Auto-select the first of the requested models that is now downloaded
                    for choice in models:
                        if choice in set(storage.get_downloaded_models()):
                            self.model_var.set(choice)
                            break
                self.after(0, _after_dl)
        threading.Thread(target=worker, daemon=True).start()
    def on_close(self) -> None:
        """Cleanup before window close."""
        try:
            self._cli.stop_chat()
        except Exception:
            pass
        self.destroy()

def run_app() -> None:
    """Create and run the Tkinter app."""
    app = App()
    app.protocol('WM_DELETE_WINDOW', app.on_close)
    app.mainloop()
