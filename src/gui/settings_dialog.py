from typing import Dict, List
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QTabWidget, QWidget, QScrollArea, QFormLayout, QHBoxLayout, QPushButton, QLineEdit, QColorDialog, QLabel, QMessageBox, QFrame, QSizePolicy, QCheckBox
from . import styles
from core import storage

class ColorPickerRow(QWidget):
    """Row with a label, color preview button, and hex input for a single theme key."""
    changed = Signal(str, str)
    def __init__(self, key: str, value: str, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._key = key
        self._btn = QPushButton()
        self._btn.setFixedSize(26, 26)
        self._btn.clicked.connect(self._pick)
        self._edit = QLineEdit(value)
        self._edit.setPlaceholderText('#RRGGBB')
        try:
            self._edit.setMaximumWidth(120)
            self._edit.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        except Exception:
            pass
        self._edit.textChanged.connect(self._on_text)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(6)
        lay.addStretch(1)
        lay.addWidget(self._btn, 0)
        lay.addWidget(self._edit, 1)
        try:
            lay.setAlignment(self._btn, Qt.AlignVCenter)
        except Exception:
            pass
        self._apply_button_color(value)
    def _apply_button_color(self, val: str) -> None:
        c = QColor(val) if QColor.isValidColor(val) else QColor('#000000')
        self._btn.setStyleSheet(f'background:{c.name()}; border:1px solid rgba(255,255,255,0.2); border-radius:4px;')
    def _pick(self) -> None:
        cur = self._edit.text().strip()
        col = QColor(cur) if QColor.isValidColor(cur) else QColor('#000000')
        chosen = QColorDialog.getColor(col, self, f'Select color for {self._key}')
        if chosen.isValid():
            self._edit.setText(chosen.name())
    def _on_text(self, txt: str) -> None:
        if QColor.isValidColor(txt):
            self._apply_button_color(txt)
            self.changed.emit(self._key, txt)

class SettingsDialog(QDialog):
    """Settings dialog with a Theme tab supporting live preview and save/restore."""
    themeChanged = Signal(dict)
    chatShowRoleChanged = Signal(bool)
    chatShowTimestampChanged = Signal(bool)
    def __init__(self, parent: QWidget = None, initial_theme: Dict[str, str] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumWidth(900)
        self.setMinimumHeight(700)
        self._theme = dict(initial_theme or styles.get_theme())
        self._default_theme = dict(styles.get_default_theme())
        _saved = styles.read_saved_current()
        self._saved_theme = dict(_saved if _saved is not None else styles.get_theme())
        # Chat toggles current and saved baselines
        try:
            self._chat_show_role = bool(storage.get_bool('chat_show_role', True))
        except Exception:
            self._chat_show_role = True
        try:
            self._chat_show_ts = bool(storage.get_bool('chat_show_timestamp', True))
        except Exception:
            self._chat_show_ts = True
        self._saved_chat_settings = {
            'chat_show_role': bool(self._chat_show_role),
            'chat_show_timestamp': bool(self._chat_show_ts),
        }
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12,12,12,12)
        outer.setSpacing(8)
        self._tabs = QTabWidget(self)
        try:
            self._tabs.setDocumentMode(True)
        except Exception:
            pass
        outer.addWidget(self._tabs, 1)
        self._build_theme_tab()
        self._build_chat_tab()
        btns = QHBoxLayout()
        btns.setContentsMargins(0,0,0,0)
        btns.setSpacing(6)
        self._save_btn = QPushButton('Save'); self._save_btn.setObjectName('TSave')
        self._restore_btn = QPushButton('Restore Defaults'); self._restore_btn.setObjectName('TRestore')
        self._close_btn = QPushButton('Close'); self._close_btn.setObjectName('TClose')
        self._save_btn.clicked.connect(self._save)
        self._restore_btn.clicked.connect(self._restore_defaults)
        # Use close() so closeEvent intercepts and prompts
        self._close_btn.clicked.connect(self.close)
        btns.addStretch(1)
        btns.addWidget(self._restore_btn)
        btns.addWidget(self._save_btn)
        btns.addWidget(self._close_btn)
        outer.addLayout(btns)
        self._refresh_button_states()
    def _sections(self) -> List[tuple]:
        return [
            ('Main App', ['APP_BG','BORDER']),
            ('App Top Bar', ['TOPBAR_BG','MODEL_BG']),
            ('Chat History', ['SIDEBAR_BG','CHAT_LIST_BG','CHAT_LIST_ITEM_SELECTED_BG']),
            ('Chat Area', ['CHAT_OUTER_BG','CHAT_INNER_BG','BUBBLE_USER','BUBBLE_AI']),
            ('Typing Area', ['TYPING_BAR_BG','TYPING_BAR_OUTLINE','TYPING_AREA_BG']),
            ('Buttons', ['NEWCHAT_BUTTON_BG','DELETE_BUTTON_BG','SEND_BG']),
            ('Text', ['TEXT_PRIMARY','TEXT_MUTED']),
        ]
    def _labels(self) -> Dict[str, str]:
        return {
            'APP_BG':'App background',
            'BORDER':'Subtle borders',
            'TOPBAR_BG':'Top bar background',
            'MODEL_BG':'Model selector background',
            'SIDEBAR_BG':'Sidebar background',
            'CHAT_LIST_BG':'Chat list background',
            'CHAT_LIST_ITEM_SELECTED_BG':'Chat item selected',
            'CHAT_OUTER_BG':'Chat area outer background',
            'CHAT_INNER_BG':'Chat area inner background',
            'BUBBLE_USER':'User bubble',
            'BUBBLE_AI':'AI bubble',
            'TYPING_BAR_BG':'Typing bar background',
            'TYPING_BAR_OUTLINE':'Typing bar outline',
            'TYPING_AREA_BG':'Typing area background',
            'NEWCHAT_BUTTON_BG':'New chat button',
            'DELETE_BUTTON_BG':'Delete button',
            'SEND_BG':'Send button',
            'TEXT_PRIMARY':'Primary text',
            'TEXT_MUTED':'Muted text',
        }
    def _editable_keys(self) -> List[str]:
        keys: List[str] = []
        for _title, group in self._sections():
            keys.extend(group)
        return keys
    def _build_theme_tab(self) -> None:
        page = QWidget()
        scroll = QScrollArea()
        try:
            scroll.setObjectName('SettingsScroll')
        except Exception:
            pass
        scroll.setWidgetResizable(True)
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(12,12,12,12)
        v.setSpacing(12)
        self._rows: List[ColorPickerRow] = []
        labels = self._labels()
        # Compute a uniform label width so color boxes align vertically across sections (wide enough to avoid wrapping)
        fm = QFontMetrics(self.font())
        try:
            all_keys: List[str] = []
            for _title, group in self._sections():
                all_keys.extend(group)
            max_label_w = max((fm.horizontalAdvance(labels.get(k, k)) for k in all_keys), default=0) + 80
        except Exception:
            max_label_w = 220
        # Build each section inside a framed container
        for title, group in self._sections():
            section = QFrame()
            section.setObjectName('SettingsSection')
            section_lay = QVBoxLayout(section)
            section_lay.setContentsMargins(12,12,12,12)
            section_lay.setSpacing(8)
            hdr = QLabel(title)
            hdr.setObjectName('SectionHeader')
            try:
                f = hdr.font(); f.setPointSize(14); f.setBold(True); hdr.setFont(f)
            except Exception:
                pass
            section_lay.addWidget(hdr, 0)
            form = QFormLayout()
            form.setContentsMargins(0,0,0,0)
            form.setSpacing(8)
            try:
                form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
            except Exception:
                pass
            try:
                form.setRowWrapPolicy(QFormLayout.DontWrapRows)
            except Exception:
                pass
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for key in group:
                val = self._theme.get(key, styles.get_theme().get(key, '#000000'))
                row = ColorPickerRow(key, val, host)
                row.changed.connect(self._on_row_changed)
                lbl = QLabel(labels.get(key, key))
                try:
                    lbl.setToolTip(key)
                except Exception:
                    pass
                try:
                    lbl.setMinimumWidth(max_label_w)
                    lbl.setWordWrap(False)
                    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                except Exception:
                    pass
                form.addRow(lbl, row)
                self._rows.append(row)
            section_lay.addLayout(form)
            v.addWidget(section)
        scroll.setWidget(host)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0,0,0,0)
        lay.setSpacing(0)
        lay.addWidget(scroll, 1)
        self._tabs.addTab(page, 'Theme')
    def _build_chat_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(12,12,12,12)
        v.setSpacing(8)
        form = QFormLayout()
        form.setContentsMargins(0,0,0,0)
        form.setSpacing(8)
        try:
            form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        except Exception:
            pass
        # Show Role checkbox
        self._cb_role = QCheckBox('Show Chat Role')
        try:
            self._cb_role.setChecked(bool(self._chat_show_role))
        except Exception:
            pass
        self._cb_role.toggled.connect(self._on_chat_role_toggled)
        form.addRow(self._cb_role)
        # Show Timestamp checkbox
        self._cb_ts = QCheckBox('Show Chat Timestamp')
        try:
            self._cb_ts.setChecked(bool(self._chat_show_ts))
        except Exception:
            pass
        self._cb_ts.toggled.connect(self._on_chat_ts_toggled)
        form.addRow(self._cb_ts)
        v.addLayout(form)
        v.addStretch(1)
        self._tabs.addTab(page, 'Chat')
    def _on_row_changed(self, key: str, value: str) -> None:
        self._theme[key] = value
        self._apply_preview()
        self._refresh_button_states()
    def _on_chat_role_toggled(self, v: bool) -> None:
        self._chat_show_role = bool(v)
        try:
            self.chatShowRoleChanged.emit(bool(v))
        except Exception:
            pass
        self._refresh_button_states()
    def _on_chat_ts_toggled(self, v: bool) -> None:
        self._chat_show_ts = bool(v)
        try:
            self.chatShowTimestampChanged.emit(bool(v))
        except Exception:
            pass
        self._refresh_button_states()
    def _apply_preview(self) -> None:
        """Apply a live preview stylesheet without mutating the global theme."""
        try:
            app = QApplication.instance()
            if app:
                qss = styles.regenerate_qss(self._theme)
                app.setStyleSheet(qss)
        except Exception:
            pass
    def _apply_live(self) -> None:
        """Commit the theme globally and apply the resulting stylesheet."""
        qss = styles.set_theme(self._theme)
        try:
            app = QApplication.instance()
            if app:
                app.setStyleSheet(qss)
        except Exception:
            pass
        # Notify listeners post-commit
        try:
            self.themeChanged.emit(dict(self._theme))
        except Exception:
            pass
        self._refresh_button_states()
    def _save(self) -> None:
        # Persist only the minimal schema keys to keep theme.json clean
        try:
            keys = set(self._editable_keys())
            minimal = {k: self._theme[k] for k in keys if k in self._theme}
            if 'BORDER' in self._theme:
                minimal['BORDER'] = self._theme['BORDER']
        except Exception:
            minimal = dict(self._theme)
        styles.save_theme(minimal)
        self._saved_theme = dict(minimal)
        # Persist chat settings
        try:
            storage.set_bool('chat_show_role', bool(self._chat_show_role))
            storage.set_bool('chat_show_timestamp', bool(self._chat_show_ts))
        except Exception:
            pass
        self._saved_chat_settings = {
            'chat_show_role': bool(self._chat_show_role),
            'chat_show_timestamp': bool(self._chat_show_ts),
        }
        # Ensure applied baseline matches saved (spec: Save applies changes too)
        self._apply_live()
    def _restore_defaults(self) -> None:
        defaults = dict(self._default_theme)
        self._theme.update(defaults)
        for row in self._rows:
            if row._key in self._theme:
                row._edit.setText(self._theme[row._key])
        self._apply_preview()
        # Reset chat toggles to defaults (True)
        try:
            self._cb_role.setChecked(True)
            self._cb_ts.setChecked(True)
        except Exception:
            pass
        self._refresh_button_states()

    def _refresh_button_states(self) -> None:
        """Update Save/Restore button properties based on edit state."""
        try:
            keys = self._editable_keys()
            theme_changed_vs_saved = any(self._theme.get(k) != self._saved_theme.get(k) for k in keys)
            theme_differs_default_saved = any(self._saved_theme.get(k) != self._default_theme.get(k) for k in keys)
        except Exception:
            theme_changed_vs_saved = self._theme != self._saved_theme
            theme_differs_default_saved = self._saved_theme != self._default_theme
        chat_changed_vs_saved = bool(self._chat_show_role != self._saved_chat_settings.get('chat_show_role') or self._chat_show_ts != self._saved_chat_settings.get('chat_show_timestamp'))
        chat_differs_default = bool(self._saved_chat_settings.get('chat_show_role') != True or self._saved_chat_settings.get('chat_show_timestamp') != True)
        changed_vs_saved = bool(theme_changed_vs_saved or chat_changed_vs_saved)
        differs_default_saved = bool(theme_differs_default_saved or chat_differs_default)
        self._save_btn.setProperty('changed', bool(changed_vs_saved))
        self._restore_btn.setProperty('needsReset', bool(differs_default_saved))
        for b in (self._save_btn, self._restore_btn):
            try:
                b.style().unpolish(b); b.style().polish(b); b.update()
            except Exception:
                pass

    def reject(self) -> None:
        """Ensure Esc or programmatic reject goes through closeEvent path."""
        self.close()

    def closeEvent(self, event) -> None:
        """Prompt to save changes on close; revert to saved theme on discard."""
        # Determine if there are unsaved changes
        try:
            keys = self._editable_keys()
            theme_changed_vs_saved = any(self._theme.get(k) != self._saved_theme.get(k) for k in keys)
        except Exception:
            theme_changed_vs_saved = self._theme != self._saved_theme
        chat_changed_vs_saved = bool(self._chat_show_role != self._saved_chat_settings.get('chat_show_role') or self._chat_show_ts != self._saved_chat_settings.get('chat_show_timestamp'))
        changed_vs_saved = bool(theme_changed_vs_saved or chat_changed_vs_saved)
        if not changed_vs_saved:
            event.accept()
            try:
                self.accept()
            except Exception:
                pass
            return
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Question)
        mb.setWindowTitle('Unsaved Changes')
        mb.setText('You have unsaved changes. Do you want to save them?')
        save_btn = mb.addButton('Save', QMessageBox.AcceptRole)
        discard_btn = mb.addButton("Don't Save", QMessageBox.DestructiveRole)
        mb.setDefaultButton(save_btn)
        mb.exec()
        clicked = mb.clickedButton()
        if clicked is save_btn:
            self._save()
            event.accept()
            try:
                self.accept()
            except Exception:
                pass
            return
        elif clicked is discard_btn:
            # Revert live preview to last saved theme
            try:
                app = QApplication.instance()
                if app:
                    qss = styles.regenerate_qss(self._saved_theme)
                    app.setStyleSheet(qss)
            except Exception:
                pass
            # Revert chat toggles to last saved and emit changes
            try:
                self._cb_role.setChecked(bool(self._saved_chat_settings.get('chat_show_role', True)))
                self._cb_ts.setChecked(bool(self._saved_chat_settings.get('chat_show_timestamp', True)))
            except Exception:
                pass
            event.accept()
            try:
                self.reject()
            except Exception:
                pass
            return
        else:
            # No explicit choice (e.g., user closed the prompt). Keep dialog open.
            event.ignore()
            return
