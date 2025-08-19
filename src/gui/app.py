from collections import deque
from datetime import datetime
from typing import List, Dict, Optional
import re
import threading
import os
import subprocess
from PySide6.QtCore import Qt, QObject, Signal, QSize, QEvent, QPoint, QRect, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QListWidget, QListWidgetItem, QToolBar, QComboBox, QPushButton, QLineEdit, QTextEdit, QToolButton, QStyle, QGraphicsDropShadowEffect, QSizePolicy, QMenu, QInputDialog, QStackedLayout, QStyleOption, QStyleOptionFrame, QProxyStyle, QAbstractItemView, QMessageBox, QScrollBar, QProgressDialog, QProgressBar
from PySide6.QtGui import QFont, QColor, QIcon, QPixmap
from PySide6 import QtSvg
from .styles import QSS, APP_BG, PANEL_BG, SIDEBAR_BG, ACCENT, TEXT, INPUT_BAR_BG, CHAT_AREA_BG
from . import styles
from .settings_dialog import SettingsDialog
from .chat_widgets import ChatView
from core.foundry_cli import FoundryCLI
from core import storage

class _Bridge(QObject):
    """Signal bridge for cross-thread CLI callbacks."""
    assistant = Signal(str)
    raw = Signal(str)
    dl_line = Signal(str)
    dl_done = Signal(bool)
    rm_line = Signal(str)
    rm_done = Signal(bool)
    device_update = Signal()

class MainWindow(QMainWindow):
    """Qt main window replicating the app with modern layout/colors."""
    def __init__(self, init_backend: Optional[str] = None, init_model: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle('Local AI Chat')
        try:
            self.setWindowIcon(QIcon('src/gui/assets/logo.png'))
        except Exception:
            pass
        self.resize(1200, 800)
        try:
            app = QApplication.instance()
            if app:
                app.setStyleSheet(QSS)
        except Exception:
            pass
        self._cli = FoundryCLI()
        self._current_chat: Optional[str] = None
        self._messages: List[Dict] = []
        self._model: Optional[str] = None
        self._chat_started: bool = False
        self._models_populating: bool = False
        self._bridge = _Bridge()
        self._bridge.assistant.connect(self._on_assistant)
        self._bridge.raw.connect(self._on_raw)
        self._bridge.dl_line.connect(self._on_download_output)
        self._bridge.dl_done.connect(self._on_download_done)
        self._bridge.rm_line.connect(self._on_delete_output)
        self._bridge.rm_done.connect(self._on_delete_done)
        try:
            self._bridge.device_update.connect(self._update_device_label)
        except Exception:
            pass
        self._dl_dialog = None
        self._dl_size_str: Optional[str] = None
        self._dl_model: Optional[str] = None
        self._dl_thread: Optional[threading.Thread] = None
        self._dl_anim_timer = QTimer(self)
        try:
            self._dl_anim_timer.setInterval(120)
        except Exception:
            pass
        try:
            self._dl_anim_timer.timeout.connect(self._tick_download_anim)
        except Exception:
            pass
        self._dl_anim_value: int = 0
        self._dl_anim_dir: int = 1
        self._dl_is_determinate: bool = False
        self._dl_bytes_done: Optional[float] = None
        self._dl_bytes_total: Optional[float] = None
        self._rm_dialog = None
        self._rm_model: Optional[str] = None
        self._rm_thread: Optional[threading.Thread] = None
        self._rm_counterpart: Optional[str] = None
        self._typing = None  # {'timer':QTimer,'bubble':Bubble,'text':str,'index':int,'iso':str,'sticky':bool}
        self._assistant_waiting: bool = False
        self._typing_debounce = QTimer(self)
        try:
            self._typing_debounce.setSingleShot(True)
        except Exception:
            pass
        # Track the currently connected timeout slot so we can disconnect it safely
        self._typing_fire_slot = None
        # Track per-chat pending requests (refcount) and route responses
        self._waiting_by_chat: Dict[str, int] = {}
        self._inflight_queue = deque()  # type: deque[str]
        # Device backend detection state
        self._device_backend: Optional[str] = init_backend or 'CPU'
        self._device_model: Optional[str] = init_model
        self._gpu_debug = deque(maxlen=12)
        self._model_probe_started: bool = False
        self._startup_probe_done: bool = False
        def _apply_small_shadow(w):
            """Apply a small drop shadow to a widget."""
            eff = QGraphicsDropShadowEffect(self)
            eff.setColor(QColor(0, 0, 0, 120))
            eff.setBlurRadius(12)
            eff.setOffset(0, 4)
            w.setGraphicsEffect(eff)
        # Root
        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(24, 8, 16, 16)
        h.setSpacing(24)
        # Sidebar
        side = QFrame()
        side.setObjectName('SideBar')
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setMinimumWidth(260)
        _apply_small_shadow(side)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 8, 16, 12)
        sv.setSpacing(10)
        title = QLabel('Chat History')
        title.setObjectName('SideTitle')
        title.setFont(QFont('Segoe UI', 16, QFont.Bold))
        sv.addWidget(title, 0)
        self.list = QListWidget()
        self.list.setObjectName('ChatList')
        self.list.itemSelectionChanged.connect(self._on_select)
        try:
            self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        except Exception:
            pass
        try:
            self.list.setContextMenuPolicy(Qt.CustomContextMenu)
            self.list.customContextMenuRequested.connect(self._on_chatlist_context_menu)
        except Exception:
            pass
        sv.addWidget(self.list, 1)
        hb = QHBoxLayout()
        new_btn = QPushButton('New Chat'); new_btn.setObjectName('Secondary')
        del_btn = QPushButton('Delete'); del_btn.setObjectName('Danger')
        for b in (new_btn, del_btn):
            b.setMinimumHeight(38)
            b.setFont(QFont('Segoe UI', 16, QFont.Bold))
            b.setMinimumWidth(100)
            _apply_small_shadow(b)
        new_btn.clicked.connect(self._new_chat)
        del_btn.clicked.connect(self._delete_chat)
        for i,w in enumerate([new_btn, del_btn]):
            hb.addWidget(w)
        sv.addLayout(hb)
        h.addWidget(side, 0)
        # Main panel (entire chat area container)
        main = QFrame()
        main.setObjectName('MainPanel')
        main.setAttribute(Qt.WA_StyledBackground, True)
        mv = QVBoxLayout(main)
        mv.setContentsMargins(12, 12, 12, 12)
        mv.setSpacing(8)
        _apply_small_shadow(main)
        # Toolbar
        tb = QToolBar()
        tb.setMovable(False)
        try:
            tb.setIconSize(QSize(60, 60))
        except Exception:
            pass
        self.addToolBar(Qt.TopToolBarArea, tb)
        # Model selector icon
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.model_combo.setMinimumHeight(40)
        self.model_combo.setFont(QFont('Segoe UI', 16))
        self.model_combo.setAttribute(Qt.WA_StyledBackground, True)
        _apply_small_shadow(self.model_combo)
        model_icon = QLabel()
        try:
            pm = QPixmap('src/gui/assets/logo.png')
            if not pm.isNull():
                icon_h = max(75, self.model_combo.sizeHint().height())
                pm = pm.scaled(icon_h, icon_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                model_icon.setPixmap(pm)
                model_icon.setFixedSize(pm.size())
        except Exception:
            pass
        try:
            _sp_left = QWidget(); _sp_left.setFixedWidth(8)
            tb.addWidget(_sp_left)
        except Exception:
            pass
        tb.addWidget(model_icon)
        try:
            _sp = QWidget(); _sp.setFixedWidth(8)
            tb.addWidget(_sp)
        except Exception:
            pass
        self._model_label = QLabel('MODEL\nSELECTOR'); self._model_label.setObjectName('ModelSelectorLabel')
        self._model_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tb.addWidget(self._model_label)
        try:
            _sp2 = QWidget(); _sp2.setFixedWidth(6)
            tb.addWidget(_sp2)
        except Exception:
            pass
        tb.addWidget(self.model_combo)
        ref_tb = QToolButton(); ref_tb.setObjectName('RefreshTool'); ref_tb.setToolButtonStyle(Qt.ToolButtonIconOnly); ref_tb.setIcon(QIcon('src/gui/assets/refresh.png')); ref_tb.setToolTip('Refresh models'); ref_tb.clicked.connect(self._refresh_models)
        delm_btn = QPushButton('Delete Model'); delm_btn.setObjectName('DeleteModel'); delm_btn.clicked.connect(self._delete_model)
        delm_btn.setMinimumHeight(36); delm_btn.setFont(QFont('Segoe UI', 16, QFont.Bold)); delm_btn.setMinimumWidth(120)
        _apply_small_shadow(delm_btn)
        tb.addWidget(ref_tb)
        tb.addWidget(delm_btn)
        # Device backend labels (updated from CLI output)
        try:
            _sp_dev_l = QWidget(); _sp_dev_l.setFixedWidth(10)
            tb.addWidget(_sp_dev_l)
        except Exception:
            pass
        self.device_title_label = QLabel('<b>Hardware<br>Acceleration</b>')
        try:
            self.device_title_label.setObjectName('DeviceLabelTitle')
            self.device_title_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
            self.device_title_label.setTextFormat(Qt.RichText)
        except Exception:
            pass
        tb.addWidget(self.device_title_label)
        try:
            _sp_dev_mid = QWidget(); _sp_dev_mid.setFixedWidth(6)
            tb.addWidget(_sp_dev_mid)
        except Exception:
            pass
        self.device_value_label = QLabel('---')
        try:
            # Keep legacy CSS name for styling consistency
            self.device_value_label.setObjectName('DeviceLabel')
            self.device_value_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.device_value_label.setTextFormat(Qt.RichText)
        except Exception:
            pass
        tb.addWidget(self.device_value_label)
        # Set an immediate baseline so the UI never shows '---'
        try:
            self.device_value_label.setText('CPU')
        except Exception:
            pass
        # Push following items to the far right
        try:
            _spacer = QWidget(); _spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            tb.addWidget(_spacer)
        except Exception:
            pass
        # Settings button in top-right corner
        settings_btn = QToolButton(); settings_btn.setObjectName('SettingsTool')
        settings_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        try:
            settings_icon = QIcon('src/gui/assets/settings.png')
            settings_btn.setIcon(settings_icon)
        except Exception:
            pass
        settings_btn.setToolTip('Settings')
        settings_btn.clicked.connect(self._open_settings)
        tb.addWidget(settings_btn)
        # Chat view wrapped in a rounded board (inner), with an external scrollbar (outer gutter)
        chat_board = QFrame(); chat_board.setObjectName('ChatBoard'); chat_board.setAttribute(Qt.WA_StyledBackground, True)
        cbv = QVBoxLayout(chat_board)
        cbv.setContentsMargins(0, 0, 0, 0)
        self.chat = ChatView(); cbv.addWidget(self.chat, 1)
        # Initialize chat visibility toggles from persistent settings
        try:
            show_role = bool(storage.get_bool('chat_show_role', True))
        except Exception:
            show_role = True
        try:
            show_ts = bool(storage.get_bool('chat_show_timestamp', True))
        except Exception:
            show_ts = True
        try:
            self.chat.set_show_role(show_role)
            self.chat.set_show_timestamp(show_ts)
        except Exception:
            pass
        try:
            self.chat.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        except Exception:
            pass
        chat_wrap = QWidget(); chat_wrap.setObjectName('ChatWrap')
        chw = QHBoxLayout(chat_wrap); chw.setContentsMargins(0, 0, 1, 0); chw.setSpacing(6)
        chw.addWidget(chat_board, 1)
        self._chat_outer_vscroll = QScrollBar(Qt.Vertical, chat_wrap); self._chat_outer_vscroll.setObjectName('ChatOuterScroll')
        try:
            self._chat_outer_vscroll.setFixedWidth(5)
        except Exception:
            pass
        # sync external scrollbar with internal
        self._syncing_scroll = False
        def _on_ext_scroll(v: int) -> None:
            if self._syncing_scroll:
                return
            self._syncing_scroll = True
            try:
                self.chat.verticalScrollBar().setValue(int(v))
            except Exception:
                pass
            self._syncing_scroll = False
        def _on_chat_scroll(v: int) -> None:
            if self._syncing_scroll:
                return
            self._syncing_scroll = True
            try:
                self._chat_outer_vscroll.setValue(int(v))
            except Exception:
                pass
            self._syncing_scroll = False
        def _on_range_changed(min_v: int, max_v: int) -> None:
            try:
                self._chat_outer_vscroll.setRange(int(min_v), int(max_v))
                self._chat_outer_vscroll.setPageStep(self.chat.verticalScrollBar().pageStep())
            except Exception:
                pass
        try:
            vb = self.chat.verticalScrollBar()
            self._chat_outer_vscroll.valueChanged.connect(_on_ext_scroll)
            vb.valueChanged.connect(_on_chat_scroll)
            vb.rangeChanged.connect(_on_range_changed)
            _on_range_changed(vb.minimum(), vb.maximum())
            self._chat_outer_vscroll.setValue(vb.value())
        except Exception:
            pass
        chw.addWidget(self._chat_outer_vscroll, 0)
        mv.addWidget(chat_wrap, 1)
        # Input
        input_bar = QFrame(); input_bar.setObjectName('InputBar'); input_bar.setAttribute(Qt.WA_StyledBackground, True)
        in_h = QHBoxLayout(input_bar)
        # Ensure card color is applied regardless of platform style
        input_bar.setStyleSheet(f"QFrame#InputBar {{ background-color: {INPUT_BAR_BG}; border: 1px solid rgba(255, 255, 255, 0.07); border-radius: 12px; }}")
        entry_wrap = QFrame(); entry_wrap.setObjectName('EntryWrap'); entry_wrap.setAttribute(Qt.WA_StyledBackground, True)
        wrap_h = QHBoxLayout(entry_wrap)
        wrap_h.setContentsMargins(0, 0, 0, 0)
        wrap_h.setSpacing(6)
        entry_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        class _SendTextEdit(QTextEdit):
            submit = Signal()
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setAcceptRichText(False)
                self.setPlaceholderText('Type a message…')
                self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                self.setFont(QFont('Segoe UI', 16))
                self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                self.setFrameShape(QFrame.NoFrame)
                self.setViewportMargins(0, 0, 0, 0)
                self.setContentsMargins(0, 0, 0, 0)
                try:
                    self.document().setDocumentMargin(3)
                except Exception:
                    pass
            def keyPressEvent(self, e):
                if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
                    e.accept(); self.submit.emit(); return
                return super().keyPressEvent(e)
        self.entry = _SendTextEdit()
        self.entry.submit.connect(self._send)
        self.entry.textChanged.connect(self._on_entry_changed)
        self.entry.document().documentLayout().documentSizeChanged.connect(lambda _sz: self._auto_resize_entry())
        wrap_h.addWidget(self.entry, 1)
        self._auto_resize_entry()
        in_h.addWidget(entry_wrap, 1)
        # Send button to the right of the input
        self.send_btn = QToolButton(); self.send_btn.setObjectName('SendButton'); self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setToolButtonStyle(Qt.ToolButtonIconOnly); self.send_btn.setAutoRaise(False)
        self.send_btn.setIcon(QIcon('src/gui/assets/send.png')); self.send_btn.setIconSize(QSize(26, 26))
        self.send_btn.clicked.connect(self._send)
        try:
            self.send_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        except Exception:
            pass
        try:
            self.send_btn.setEnabled(True)
        except Exception:
            pass
        # Colors come from QSS; only set dynamic radius/padding at runtime
        self.send_btn.setStyleSheet("QToolButton#SendButton { border: 0px; border-radius: 15px; padding: 6px; }")
        in_h.addWidget(self.send_btn, 0)
        try:
            in_h.setAlignment(self.send_btn, Qt.AlignVCenter)
        except Exception:
            pass
        try:
            self._auto_resize_entry()
        except Exception:
            pass
        mv.addWidget(input_bar)
        h.addWidget(main, 1)
        # Populate model selector on startup
        try:
            self._refresh_models()
        except Exception:
            pass
        # Kick immediate startup GPU probe only if GPU backend present but model missing
        try:
            be_low = (self._device_backend or '').lower()
            if 'gpu' in be_low and not self._device_model:
                QTimer.singleShot(0, self._startup_device_probe)
        except Exception:
            pass
        # Data
        self._load_chats()
        # Ensure an initial baseline label (CPU) is shown before any detection results
        try:
            self._update_device_label()
        except Exception:
            pass
        # Defer a second update to ensure UI is fully constructed before updating the label
        try:
            QTimer.singleShot(0, self._update_device_label)
        except Exception:
            pass
    def _on_chatlist_context_menu(self, pos: QPoint) -> None:
        try:
            menu = QMenu(self.list)
            act_all = menu.addAction('Select All')
            if self.list.count() == 0:
                act_all.setEnabled(False)
            act_all.triggered.connect(lambda _=False: self.list.selectAll())
            gp = self.list.mapToGlobal(pos)
            menu.exec(gp)
        except Exception:
            pass
        self._refresh_models()
    def closeEvent(self, e) -> None:
        # Stop typing animation/timers and hide indicator
        try:
            if self._typing and isinstance(self._typing, dict):
                tmr = self._typing.get('timer')
                if tmr:
                    tmr.stop()
        except Exception:
            pass
        self._typing = None
        try:
            self._typing_debounce.stop()
        except Exception:
            pass
        self._assistant_waiting = False
        try:
            self.chat.hide_typing()
        except Exception:
            pass
        # Ensure backend request is cancelled
        try:
            self._cli.stop_chat()
        except Exception:
            pass
        return super().closeEvent(e)
    def _fmt_ts(self, iso: Optional[str] = None) -> str:
        """Format timestamp to 'Jan. 1, 2025 - 01:50:45 AM'."""
        try:
            dt = datetime.fromisoformat(iso) if iso else datetime.now()
        except Exception:
            dt = datetime.now()
        month = dt.strftime('%b') + '.'
        return f"{month} {dt.day}, {dt.year} - {dt.strftime('%I:%M:%S %p')}"
    # --- Chat list ---
    def _load_chats(self) -> None:
        # Preserve selection
        sel_id: Optional[str] = None
        items = self.list.selectedItems()
        if items:
            sel_id = items[0].data(Qt.UserRole)
        self.list.clear()
        for meta in storage.list_chats():
            cid = meta['id']
            title = meta['title']
            it = QListWidgetItem()
            it.setData(Qt.UserRole, cid)
            it.setSizeHint(QSize(200, 40))
            row = QWidget()
            lh = QHBoxLayout(row); lh.setContentsMargins(8, 0, 0, 0); lh.setSpacing(4)
            title_edit = QLineEdit(title)
            title_edit.setObjectName('ChatTitle')
            title_edit.setReadOnly(True)
            title_edit.setFrame(False)
            title_edit.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            title_edit.setTextMargins(0, 0, 0, 16)
            title_edit.setFocusPolicy(Qt.NoFocus)
            title_edit.setCursor(Qt.ArrowCursor)
            title_edit.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            title_edit.setStyleSheet('border:0px; background:transparent; padding:0px; margin:0px; min-height:0px; height:auto; padding-top:0px; padding-bottom:0px;')
            try:
                fm = title_edit.fontMetrics()
                fixed_h = max(28, fm.height() + 10)
                title_edit.setFixedHeight(fixed_h)
            except Exception:
                pass
            btn = QToolButton(row)
            btn.setObjectName('Kebab')
            btn.setText('⋮')
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setFixedWidth(22)
            menu = QMenu(btn)
            act_ren = menu.addAction('Rename')
            act_del = menu.addAction('Delete')
            act_ren.triggered.connect(lambda _=False, chat_id=cid: self._start_inline_rename(chat_id))
            act_del.triggered.connect(lambda _=False, chat_id=cid: self._delete_chat_by_id(chat_id))
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.InstantPopup)
            try:
                btn.pressed.connect(lambda _=False, chat_id=cid: self._select_chat_by_id(chat_id))
            except Exception:
                pass
            lh.addWidget(title_edit, 1)
            try:
                lh.setAlignment(title_edit, Qt.AlignVCenter)
            except Exception:
                pass
            try:
                h_row = max(title_edit.height() + 8, 42)
                it.setSizeHint(QSize(200, h_row))
            except Exception:
                pass
            lh.addWidget(btn, 0, Qt.AlignRight | Qt.AlignTop)
            self.list.addItem(it)
            self.list.setItemWidget(it, row)
        if self.list.count() > 0:
            if sel_id is not None:
                for i in range(self.list.count()):
                    if self.list.item(i).data(Qt.UserRole) == sel_id:
                        self.list.setCurrentRow(i)
                        break
                else:
                    self.list.setCurrentRow(0)
            else:
                self.list.setCurrentRow(0)
    def _on_select(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        cid = items[0].data(Qt.UserRole)
        prev_cid = self._current_chat
        data = storage.load_chat(cid)
        if not data:
            return
        # If an animation was running in the previous chat, finalize and persist it
        if prev_cid and self._typing and isinstance(self._typing, dict):
            try:
                tmr = self._typing.get('timer')
                if tmr:
                    tmr.stop()
            except Exception:
                pass
            try:
                s = self._typing.get('text', '')
                iso = self._typing.get('iso') or datetime.now().isoformat()
                prev_data = storage.load_chat(prev_cid) or {}
                msgs = list(prev_data.get('messages', []))
                msgs.append({'role':'assistant','content':s,'ts':iso})
                storage.save_messages(prev_cid, msgs)
            except Exception:
                pass
            self._typing = None
        self._current_chat = cid
        self._messages = data.get('messages', [])
        self.chat._v.setEnabled(False)
        while self.chat._v.count() > 1:
            w = self.chat._v.itemAt(0).widget()
            if w:
                w.deleteLater()
            self.chat._v.removeItem(self.chat._v.itemAt(0))
        try:
            self.chat.reset_day_groups()
        except Exception:
            pass
        for m in self._messages:
            role = m.get('role','assistant')
            txt = m.get('content','')
            iso = m.get('ts')
            self.chat.add_message(role, txt, iso, animate=False)
        # Show or hide typing indicator based on per-chat waiting state
        try:
            if int(self._waiting_by_chat.get(cid, 0)) > 0:
                self.chat.show_typing(sticky=True)
            else:
                self.chat.hide_typing()
        except Exception:
            pass
        self.chat._v.setEnabled(True)
        def _scroll_on_open() -> None:
            try:
                self.chat.scroll_to_bottom()
            except Exception:
                pass
        try:
            QTimer.singleShot(0, _scroll_on_open)
            QTimer.singleShot(16, _scroll_on_open)
            QTimer.singleShot(100, _scroll_on_open)
        except Exception:
            pass
    def _new_chat(self) -> None:
        cid = storage.create_chat('New Chat')
        self._load_chats()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == cid:
                self.list.setCurrentRow(i)
                break
    def _rename_chat(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        cid = items[0].data(Qt.UserRole)
        self._start_inline_rename(cid)
    def _start_inline_rename(self, cid: str) -> None:
        """Start inline rename for a chat row using the row's persistent QLineEdit without geometry swaps."""
        def _content_top(w: QLineEdit) -> int:
            opt = QStyleOptionFrame(); opt.initFrom(w)
            try:
                r = w.style().subElementRect(QStyle.SE_LineEditContents, opt, w)
                return int(r.top())
            except Exception:
                return 0
        class _ShiftStyle(QProxyStyle):
            def __init__(self, base, dy: int):
                super().__init__(base)
                self._dy = int(dy)
            def subElementRect(self, element, option, widget):
                r = super().subElementRect(element, option, widget)
                if element == QStyle.SE_LineEditContents and isinstance(widget, QLineEdit) and self._dy:
                    r.translate(0, -self._dy)
                return r
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) != cid:
                continue
            row = self.list.itemWidget(it)
            if not row:
                return
            edit = row.findChild(QLineEdit, 'ChatTitle')
            if not edit:
                return
            if edit.property('editing'):
                return
            edit.setProperty('editing', True)
            orig_text = edit.text()
            # capture baseline top before editing
            top_before = _content_top(edit)
            # make it editable with identical visuals
            try:
                m = edit.textMargins()
                # PySide6 returns QMargins; extract components
                ml, mt, mr, mb = (m.left(), m.top(), m.right(), m.bottom())
            except Exception:
                ml, mt, mr, mb = 0, 0, 0, 0
            try:
                edit.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            except Exception:
                pass
            edit.setReadOnly(False)
            edit.setFocusPolicy(Qt.StrongFocus)
            edit.setCursor(Qt.IBeamCursor)
            edit.setFrame(False)
            edit.setTextMargins(ml, mt, mr, mb)
            edit.setStyleSheet('border:0px; background:transparent; padding:0px; margin:0px; min-height:0px; height:auto; padding-top:0px; padding-bottom:0px;')
            # compute delta and install proxy style to shift contents up by delta
            top_after = _content_top(edit)
            delta = int(top_after - top_before)
            orig_style = edit.style()
            dy = delta
            proxy = _ShiftStyle(orig_style, dy) if dy else None
            if proxy:
                edit.setStyle(proxy)
            done = {'v': False}
            def _teardown() -> None:
                try:
                    if proxy:
                        base = proxy.baseStyle() or QApplication.style()
                        edit.setStyle(base)
                except Exception:
                    pass
                edit.setReadOnly(True)
                edit.setFocusPolicy(Qt.NoFocus)
                edit.setCursor(Qt.ArrowCursor)
                edit.setProperty('editing', False)
                try:
                    edit.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                except Exception:
                    pass
            def _commit() -> None:
                if done['v']:
                    return
                done['v'] = True
                new_title = edit.text().strip()
                try:
                    if new_title and new_title != orig_text:
                        storage.rename_chat(cid, new_title)
                    elif not new_title:
                        edit.setText(orig_text)
                except Exception:
                    pass
                if app is not None:
                    try:
                        app.removeEventFilter(filter_obj)
                    except Exception:
                        pass
                _teardown()
            app = QApplication.instance()
            class _ClickAwayFilter(QObject):
                def eventFilter(self, obj, ev):
                    if ev.type() == QEvent.MouseButtonPress:
                        try:
                            gp = getattr(ev, 'globalPosition', None)
                            if gp is not None:
                                gpt = gp().toPoint() if callable(gp) else gp.toPoint()
                            else:
                                gpt = ev.globalPos() if hasattr(ev, 'globalPos') else None
                            if gpt is not None:
                                lp = edit.mapFromGlobal(gpt)
                                if edit.rect().contains(lp):
                                    return False
                            _commit()
                        except Exception:
                            _commit()
                    return False
            filter_obj = _ClickAwayFilter(self)
            if app is not None:
                app.installEventFilter(filter_obj)
            edit.setFocus()
            edit.selectAll()
            edit.returnPressed.connect(_commit)
            edit.editingFinished.connect(_commit)
            break
    def _delete_chat(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        ids = [it.data(Qt.UserRole) for it in items if it is not None]
        if not ids:
            return
        n = len(ids)
        title = 'Confirm Delete'
        msg = 'Are you sure you want to delete the selected chat?' if n == 1 else f'Are you sure you want to delete these {n} chats?'
        try:
            resp = QMessageBox.question(self, title, msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        except Exception:
            resp = QMessageBox.No
        if resp != QMessageBox.Yes:
            return
        self._delete_chats_by_ids(ids)
    def _rename_chat_by_id(self, cid: str) -> None:
        current = storage.load_chat(cid) or {}
        current_title = current.get('title', 'Chat')
        new_title, ok = QInputDialog.getText(self, 'Rename Chat', 'New name:', text=current_title)
        if not ok:
            return
        title = new_title.strip() or current_title
        storage.rename_chat(cid, title)
        self._load_chats()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == cid:
                self.list.setCurrentRow(i)
                break
    def _delete_chat_by_id(self, cid: str) -> None:
        storage.delete_chat(cid)
        if self._current_chat == cid:
            # Stop typing animation/timers and hide indicator
            try:
                if self._typing and isinstance(self._typing, dict):
                    tmr = self._typing.get('timer')
                    if tmr:
                        tmr.stop()
            except Exception:
                pass
            self._typing = None
            try:
                self._typing_debounce.stop()
            except Exception:
                pass
            self._assistant_waiting = False
            try:
                self.chat.hide_typing()
            except Exception:
                pass
            # Cancel backend request tied to this chat
            try:
                self._cli.stop_chat()
            except Exception:
                pass
            self._chat_started = False
            self._current_chat = None
            self._messages = []
            while self.chat._v.count() > 1:
                w = self.chat._v.itemAt(0).widget()
                if w:
                    w.deleteLater()
                self.chat._v.removeItem(self.chat._v.itemAt(0))
            try:
                self.chat.reset_day_groups()
            except Exception:
                pass
            # Clear per-chat waiting/inflight state
            try:
                if cid in self._waiting_by_chat:
                    self._waiting_by_chat.pop(cid, None)
                if cid in self._inflight_queue:
                    self._inflight_queue.remove(cid)
            except Exception:
                pass
        else:
            # If deleting a non-current chat that still has pending/inflight, cancel backend and clear counters
            pending = False
            try:
                pending = int(self._waiting_by_chat.get(cid, 0)) > 0 or (cid in self._inflight_queue)
            except Exception:
                pending = True
            if pending:
                try:
                    self._cli.stop_chat()
                except Exception:
                    pass
                self._chat_started = False
                try:
                    if cid in self._waiting_by_chat:
                        self._waiting_by_chat.pop(cid, None)
                    if cid in self._inflight_queue:
                        self._inflight_queue.remove(cid)
                except Exception:
                    pass
        self._load_chats()
    def _delete_chats_by_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        clear_view = self._current_chat in set(ids)
        for cid in ids:
            try:
                storage.delete_chat(cid)
            except Exception:
                pass
        # If deleting the current chat or any chat with pending work, stop typing and cancel backend
        try:
            any_pending = any(int(self._waiting_by_chat.get(cid, 0)) > 0 or (cid in self._inflight_queue) for cid in ids)
        except Exception:
            any_pending = True if clear_view else False
        if clear_view or any_pending:
            # Stop typing animation/timers and hide indicator
            try:
                if self._typing and isinstance(self._typing, dict):
                    tmr = self._typing.get('timer')
                    if tmr:
                        tmr.stop()
            except Exception:
                pass
            self._typing = None
            try:
                self._typing_debounce.stop()
            except Exception:
                pass
            self._assistant_waiting = False
            try:
                self.chat.hide_typing()
            except Exception:
                pass
            # Cancel backend request
            try:
                self._cli.stop_chat()
            except Exception:
                pass
            self._chat_started = False
        if clear_view:
            self._current_chat = None
            self._messages = []
            while self.chat._v.count() > 1:
                w = self.chat._v.itemAt(0).widget()
                if w:
                    w.deleteLater()
                self.chat._v.removeItem(self.chat._v.itemAt(0))
            try:
                self.chat.reset_day_groups()
            except Exception:
                pass
            # Clear per-chat waiting/inflight state
            try:
                for cid in ids:
                    if cid in self._waiting_by_chat:
                        self._waiting_by_chat.pop(cid, None)
                if self._inflight_queue:
                    self._inflight_queue = deque([x for x in self._inflight_queue if x not in set(ids)])
            except Exception:
                pass
        self._load_chats()
    # --- Models ---
    def _refresh_models(self) -> None:
        self._models_populating = True
        try:
            names = self._cli.list_models() or []
        except Exception:
            names = []
        # Merge downloaded registry with actual cache
        try:
            pairs = self._cli.list_cached_pairs()
        except Exception:
            pairs = []
        try:
            storage.migrate_downloaded_aliases(pairs)
        except Exception:
            pass
        try:
            reg = set(storage.get_downloaded_models())
        except Exception:
            reg = set()
        cached_ids = {mid for _, mid in pairs}
        downloaded_set = set(reg) | set(cached_ids)
        # Persist union so UI stays in sync on next run
        try:
            if downloaded_set != reg:
                storage.set_downloaded_models(sorted(downloaded_set))
        except Exception:
            pass
        available = [n for n in names if n not in downloaded_set]
        # Rebuild combo without emitting change signals
        try:
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            downloaded_list = sorted(downloaded_set)
            if downloaded_list and available:
                self.model_combo.addItems(downloaded_list)
                self.model_combo.addItem('────────────')
                self.model_combo.addItems(available)
            elif downloaded_list:
                self.model_combo.addItems(downloaded_list)
            elif available:
                self.model_combo.addItems(available)
            else:
                try:
                    self.model_combo.setPlaceholderText('No models found')
                except Exception:
                    pass
            # Selection policy: only preselect if there are downloaded models
            if downloaded_list:
                try:
                    self.model_combo.setCurrentText(downloaded_list[0])
                except Exception:
                    pass
            else:
                try:
                    self.model_combo.setCurrentIndex(-1)
                    self.model_combo.setPlaceholderText('Select a model')
                except Exception:
                    pass
        finally:
            try:
                self.model_combo.blockSignals(False)
            except Exception:
                pass
            self._models_populating = False
    def _delete_model(self) -> None:
        name = self.model_combo.currentText()
        if not name or '─' in name:
            return
        title = 'Confirm Delete Model'
        msg = f'Are you sure you want to delete the model "{name}"?'
        try:
            resp = QMessageBox.question(self, title, msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        except Exception:
            resp = QMessageBox.No
        if resp != QMessageBox.Yes:
            return
        self._rm_model = name
        # Resolve alias/id counterpart to clean registry later
        self._rm_counterpart = None
        try:
            pairs = self._cli.list_cached_pairs()
            alias_to_id = {a: mid for a, mid in pairs}
            id_to_alias = {mid: a for a, mid in pairs}
            self._rm_counterpart = alias_to_id.get(name) or id_to_alias.get(name)
        except Exception:
            self._rm_counterpart = None
        # Build deletion progress dialog
        try:
            dlg = QProgressDialog(self)
            dlg.setWindowTitle('Deletion in Progress...')
            dlg.setCancelButton(None)
            dlg.setRange(0, 0)
            dlg.setValue(0)
            dlg.setMinimumDuration(0)
            dlg.setWindowModality(Qt.ApplicationModal)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            label = f'Deleting {name} – preparing…'
            dlg.setLabelText(label)
            try:
                dlg.setMinimumWidth(560)
            except Exception:
                pass
            try:
                lay = dlg.layout()
                if lay:
                    lay.setContentsMargins(12, 12, 12, 12)
                    lay.setSpacing(8)
            except Exception:
                pass
            try:
                bar = dlg.findChild(QProgressBar)
                if bar:
                    bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    bar.setMinimumHeight(18)
            except Exception:
                pass
            try:
                lbl = dlg.findChild(QLabel)
                if lbl:
                    lbl.setWordWrap(True)
                    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            except Exception:
                pass
            self._rm_dialog = dlg
        except Exception:
            self._rm_dialog = None
        # Start background deletion with streamed output
        def _runner() -> None:
            ok = False
            try:
                ok = bool(self._cli.remove_cached_model_stream(name, on_output=lambda s: self._bridge.rm_line.emit(s)))
            except Exception:
                ok = False
            try:
                self._bridge.rm_done.emit(bool(ok))
            except Exception:
                pass
        t = threading.Thread(target=_runner, daemon=True)
        self._rm_thread = t
        try:
            t.start()
        except Exception:
            pass
        try:
            if self._rm_dialog is not None:
                self._rm_dialog.show()
        except Exception:
            pass
    def _on_model_changed(self, s: str) -> None:
        if getattr(self, '_models_populating', False):
            return
        if not s or '─' in s:
            self._model = None
            return
        self._model = s
        # Reset device labels on model change
        try:
            self._device_backend = None
            self._device_model = None
            self._model_probe_started = False
            if hasattr(self, 'device_value_label') and self.device_value_label is not None:
                self.device_value_label.setText('---')
        except Exception:
            pass
        # If model isn't downloaded, prompt to download with progress
        try:
            downloaded = set(storage.get_downloaded_models())
        except Exception:
            downloaded = set()
        if s not in downloaded:
            try:
                self._start_download_model(s)
            except Exception:
                pass
        # stop any running chat on model change
        try:
            self._cli.stop_chat()
        except Exception:
            pass
        self._chat_started = False

    def _on_raw(self, line: str) -> None:
        """Parse raw CLI output lines to detect backend and GPU model, then update label."""
        new_backend = None
        new_model = None
        # Always collect potential GPU-related lines for tooltip diagnostics
        try:
            self._maybe_collect_gpu_debug(line)
        except Exception:
            pass
        try:
            new_backend = self._detect_device_backend(line)
        except Exception:
            new_backend = None
        try:
            new_model = self._detect_device_model(line)
        except Exception:
            new_model = None
        # Fallback: if GUI regex didn't extract a backend, try the CLI's internal detector
        if not new_backend and not self._device_backend:
            try:
                cli_backend = self._cli.get_device_backend()
                if cli_backend:
                    new_backend = cli_backend
            except Exception:
                pass
        # Fallback: if GUI regex didn't extract a model, try the CLI's internal detector
        if not new_model and not self._device_model:
            try:
                cli_model = self._cli.get_device_model()
                if cli_model:
                    new_model = cli_model
            except Exception:
                pass
        changed = False
        # Do not downgrade from a known GPU backend to CPU based on weak/early lines
        try:
            cur_be = self._device_backend or ''
            cur_is_gpu = 'gpu' in cur_be.lower()
            new_is_gpu = 'gpu' in (new_backend.lower() if new_backend else '')
            if new_backend and cur_is_gpu and not new_is_gpu:
                new_backend = None
        except Exception:
            pass
        if new_backend and new_backend != self._device_backend:
            self._device_backend = new_backend
            changed = True
        if new_model and new_model != self._device_model:
            self._device_model = new_model
            changed = True
        # If currently no model but GPU backend is known, kick off a system-level probe once
        try:
            self._maybe_kick_model_probe()
        except Exception:
            pass
        if not changed:
            return
        try:
            self._update_device_label()
        except Exception:
            pass

    def _detect_device_backend(self, s: str) -> Optional[str]:
        """Return a normalized accelerator name if the line indicates device backend."""
        try:
            txt = s.strip()
        except Exception:
            txt = s or ''
        low = txt.lower()
        # Strong signal: explicit Device: header
        m = re.match(r"\s*acceleration\s*[:=]\s*(.+)$", txt, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            return self._normalize_backend_name(val)
        # Strong signal: line mentions accelerator and looks like a header
        if any(k in low for k in ('accelerator', 'backend', 'runtime')) and any(k in low for k in ('cuda','directml','dml','rocm','mps','metal','openvino','cpu','gpu')):
            return self._normalize_backend_name(txt)
        # Model ID hint line
        if 'model id' in low and any(x in low for x in ('-cuda-gpu','-dml-gpu','-rocm-gpu','-cpu','-metal-gpu','-mps')):
            return self._normalize_backend_name(txt)
        # Generic mention but with GPU-specific keywords
        if any(k in low for k in ('cuda','directml',' dml ','rocm','mps','metal','openvino')):
            return self._normalize_backend_name(txt)
        return None

    def _detect_device_model(self, s: str) -> Optional[str]:
        """Extract a GPU model name from CLI output when present."""
        try:
            txt = (s or '').strip()
        except Exception:
            txt = s or ''
        if not txt:
            return None
        low = txt.lower()
        pats = [
            # Selected/using adapter or device with explicit separator
            re.compile(r"(?:selected|using)\s+(?:cuda\s+|d3d12\s+)?(?:adapter|device)\s*[:=]\s*['\"]?(.+?)['\"]?(?:\s|$)", re.IGNORECASE),
            # CUDA/DirectML mentions with device/gpu and a separator
            re.compile(r"(?:cuda|nvidia).*(?:device|gpu)\s*[:=]\s*['\"]?(.+?)['\"]?(?:\s|$)", re.IGNORECASE),
            re.compile(r"(?:directml|dml).*(?:device)\s*[:=]\s*['\"]?(.+?)['\"]?(?:\s|$)", re.IGNORECASE),
            # 'device 0: NVIDIA GeForce ...' or 'adapter-1 - AMD Radeon ...'
            re.compile(r"(?:adapter|device)\s*\d*\s*[:\-]\s*['\"]?(.+?)['\"]?(?:\s|$)", re.IGNORECASE),
            # Using/Selected device without separator
            re.compile(r"(?:using|selected)\s+(?:cuda\s+|d3d12\s+)?(?:device|adapter)\s+(?:\d+\s*)?['\"]?(.+?)['\"]?(?:\s|$)", re.IGNORECASE),
            # Generic adapter/device line that already starts with a vendor
            re.compile(r"(?:adapter|device)\s*[:=]\s*(NVIDIA.+|AMD.+|Intel.+)$", re.IGNORECASE),
            # Variants like "device 0: NVIDIA GeForce ..." or "gpu-0 - NVIDIA ..."
            re.compile(r"(?:device|gpu)\s*[-:]?\s*\d+\s*[-:]\s*(NVIDIA.+|AMD.+|Intel.+)$", re.IGNORECASE),
            # Key-value with name: NVIDIA ...
            re.compile(r"\bname\s*[:=]\s*(NVIDIA.+|AMD.+|Intel.+)$", re.IGNORECASE),
            # Bracketed adapter lines e.g., "Adapter 0: NVIDIA ... (PCI...)"
            re.compile(r"Adapter\s*\d+\s*[:-]\s*(NVIDIA.+|AMD.+|Intel.+)", re.IGNORECASE),
        ]
        for r in pats:
            m = r.search(txt)
            if m:
                return self._clean_model_name(m.group(1))
        if any(k in low for k in ('nvidia','geforce','quadro','tesla','amd','radeon','vega','intel','arc','iris')) and any(k in low for k in ('gpu','adapter','device','directml','dml','cuda','rocm','metal','mps')):
            m2 = re.search(r"(NVIDIA\s+.+|AMD\s+.+|Intel\s+.+)", txt, re.IGNORECASE)
            if m2:
                return self._clean_model_name(m2.group(1))
        return None

    def _clean_model_name(self, val: str) -> str:
        """Normalize raw adapter string to a concise GPU model name."""
        s = (val or '').strip().strip('\"\'')
        # Drop leading index/prefix like "Adapter 0:" or "Device-1:"
        try:
            s = re.sub(r"^(?:adapter|device)?\s*\d+\s*[:\-]\s*", "", s, flags=re.IGNORECASE)
        except Exception:
            pass
        # Preserve parentheses content (e.g., CUDA version); trim brackets and common separators (also comma)
        s = re.split(r"\s*\[|\s\|\s|\s-\s|\s@\s|,", s)[0].strip()
        # Strip common trailing punctuation/brackets
        s = s.rstrip(")]:;,.")
        s = s.replace('(TM)', '').replace('(R)', '').replace('®', '').replace('™', '').strip()
        s = re.sub(r"\s+", " ", s)
        return s

    def _normalize_backend_name(self, raw: str) -> Optional[str]:
        """Map arbitrary device strings into a concise label."""
        low = (raw or '').lower()
        if 'cuda' in low or 'nvidia' in low:
            return 'CUDA GPU'
        if 'directml' in low or re.search(r"\bdml\b", low):
            return 'DirectML GPU'
        if 'rocm' in low or 'amd' in low:
            return 'ROCm GPU'
        if 'mps' in low or 'metal' in low:
            return 'Metal GPU'
        if 'openvino' in low:
            return 'OpenVINO'
        if re.search(r"\bcpu\b", low):
            return 'CPU'
        if 'gpu' in low:
            return 'GPU'
        return None

    def _startup_device_probe(self) -> None:
        """Quick, non-blocking GPU probe at startup to show model/backend immediately."""
        if self._startup_probe_done:
            return
        self._startup_probe_done = True
        def _run():
            name = None
            try:
                try:
                    self._gpu_debug.append("[probe] startup GPU quick probe")
                except Exception:
                    pass
                try:
                    self._gpu_debug.append("[probe] trying nvidia-smi")
                except Exception:
                    pass
                name = self._try_nvidia_smi()
                if not name and os.name == 'nt':
                    try:
                        self._gpu_debug.append("[probe] trying PowerShell WMI (startup)")
                    except Exception:
                        pass
                    # Prefer NVIDIA first
                    name = self._try_powershell_gpu_names(prefer='nvidia') or self._try_powershell_gpu_names()
            except Exception:
                name = None
            if name:
                try:
                    clean = self._clean_model_name(name)
                except Exception:
                    clean = name
                try:
                    if not self._device_model:
                        self._device_model = clean
                    # Infer backend from vendor if not already GPU
                    low = (clean or '').lower()
                    be_low = (self._device_backend or '').lower()
                    if 'gpu' not in be_low:
                        if 'nvidia' in low:
                            self._device_backend = 'CUDA GPU'
                        elif os.name == 'nt' and ('amd' in low or 'radeon' in low or 'intel' in low or 'arc' in low or 'iris' in low):
                            self._device_backend = 'DirectML GPU'
                    try:
                        self._gpu_debug.append(f"[probe] {name}")
                    except Exception:
                        pass
                    self._bridge.device_update.emit()
                except Exception:
                    try:
                        self._bridge.device_update.emit()
                    except Exception:
                        pass
            else:
                try:
                    self._gpu_debug.append("[probe] no GPU name found at startup")
                except Exception:
                    pass
                try:
                    if not self._device_backend:
                        self._device_backend = 'CPU'
                except Exception:
                    pass
                try:
                    self._bridge.device_update.emit()
                except Exception:
                    pass
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _maybe_kick_model_probe(self) -> None:
        """Start a background system probe to get GPU model if backend is GPU but model is missing."""
        if self._model_probe_started:
            return
        be = (self._device_backend or '').lower()
        if not be:
            return
        if 'gpu' not in be:
            return
        if self._device_model:
            return
        self._model_probe_started = True
        def _run():
            name = None
            try:
                try:
                    self._gpu_debug.append("[probe] starting GPU name probe")
                except Exception:
                    pass
                if 'cuda' in be or 'nvidia' in be:
                    try:
                        self._gpu_debug.append("[probe] trying nvidia-smi")
                    except Exception:
                        pass
                    name = self._try_nvidia_smi()
                if not name:
                    try:
                        self._gpu_debug.append("[probe] trying PowerShell WMI")
                    except Exception:
                        pass
                    name = self._try_powershell_gpu_names(prefer='nvidia' if 'cuda' in be or 'nvidia' in be else None)
                if not name:
                    try:
                        self._gpu_debug.append("[probe] trying WMIC fallback")
                    except Exception:
                        pass
                    name = self._try_wmic_gpu_names(prefer='nvidia' if 'cuda' in be or 'nvidia' in be else None)
            except Exception:
                name = None
            if name:
                try:
                    clean = self._clean_model_name(name)
                except Exception:
                    clean = name
                try:
                    if not self._device_model:
                        self._device_model = clean
                        self._gpu_debug.append(f"[probe] {name}")
                        self._bridge.device_update.emit()
                except Exception:
                    pass
            else:
                try:
                    self._gpu_debug.append("[probe] no GPU name found")
                    self._bridge.device_update.emit()
                except Exception:
                    pass
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _try_nvidia_smi(self) -> Optional[str]:
        """Return first NVIDIA GPU name via nvidia-smi, if available."""
        try:
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            cp = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', timeout=3, check=False, creationflags=flags)
        except FileNotFoundError:
            return None
        except Exception:
            return None
        out = (cp.stdout or '').strip().splitlines()
        if out:
            s = out[0].strip()
            return s or None
        return None

    def _try_powershell_gpu_names(self, prefer: Optional[str] = None) -> Optional[str]:
        """Return a GPU name via PowerShell WMI (Win32_VideoController). Prefer vendor when specified."""
        if os.name != 'nt':
            return None
        try:
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            exe_list = ["powershell", "pwsh"]
            names = []
            for exe in exe_list:
                try:
                    cmd = [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
                    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', timeout=5, check=False, creationflags=flags)
                    out = [x.strip() for x in (cp.stdout or '').splitlines() if x.strip()]
                    if out:
                        names = out
                        break
                except FileNotFoundError:
                    continue
        except Exception:
            names = []
        if not names:
            return None
        # Filter out Microsoft Basic Display/Render drivers
        filt = [n for n in names if 'microsoft' not in n.lower()]
        cand = filt or names
        if prefer:
            pref = [n for n in cand if prefer.lower() in n.lower()]
            if pref:
                return pref[0]
        # Otherwise choose by vendor priority
        for v in ('NVIDIA', 'AMD', 'Intel'):
            for n in cand:
                if v.lower() in n.lower():
                    return n
        return cand[0] if cand else None

    def _try_wmic_gpu_names(self, prefer: Optional[str] = None) -> Optional[str]:
        """Return a GPU name via legacy WMIC if available."""
        if os.name != 'nt':
            return None
        try:
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            cp = subprocess.run(["wmic", "path", "win32_VideoController", "get", "name"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', timeout=5, check=False, creationflags=flags)
            lines = [x.strip() for x in (cp.stdout or '').splitlines() if x.strip()]
            if not lines:
                return None
            # Remove header if present
            if lines and lines[0].lower() == 'name':
                lines = lines[1:]
            names = [x for x in lines if x]
        except Exception:
            names = []
        if not names:
            return None
        filt = [n for n in names if 'microsoft' not in n.lower()]
        cand = filt or names
        if prefer:
            pref = [n for n in cand if prefer.lower() in n.lower()]
            if pref:
                return pref[0]
        for v in ('NVIDIA', 'AMD', 'Intel'):
            for n in cand:
                if v.lower() in n.lower():
                    return n
        return cand[0] if cand else None

    def _update_device_label(self) -> None:
        """Update the device value label with GPU/CPU and model; GPU shows on two lines."""
        if not hasattr(self, 'device_value_label') or self.device_value_label is None:
            return
        backend = self._device_backend or ''
        model = self._device_model or ''
        is_gpu = 'gpu' in backend.lower() if backend else False
        if is_gpu and not model:
            try:
                self._maybe_kick_model_probe()
            except Exception:
                pass
        # Always render a compact label: GPU or CPU
        text = 'GPU' if is_gpu else 'CPU'
        try:
            self.device_value_label.setText(text)
        except Exception:
            pass
        try:
            tips: list[str] = []
            if is_gpu:
                if backend:
                    tips.append(f"Backend: {backend}")
                if model:
                    tips.append(f"Model: {model}")
                if self._gpu_debug:
                    tips.append("Samples:")
                    tips.extend(list(self._gpu_debug))
                if not tips:
                    tips.append('GPU acceleration is active.')
            else:
                tips.append('Running on CPU. If your computer has a GPU, please ensure NVIDIA drivers and CUDA are installed. Using GPU acceleration should result in faster responses.')
            self.device_value_label.setToolTip("\n".join(tips))
        except Exception:
            pass

    def _maybe_collect_gpu_debug(self, s: str) -> None:
        """Collect GPU-related lines to help refine detection regex and show in tooltip."""
        try:
            txt = (s or '').strip()
        except Exception:
            txt = s or ''
        if not txt:
            return
        low = txt.lower()
        # Exclude noisy cache/download lines
        if ('model ' in low and 'found in the local cache' in low) or any(k in low for k in ('downloading','verifying','extracting','fetching')):
            return
        # Collect broadly: vendor OR device context keywords
        if any(k in low for k in ('nvidia','geforce','quadro','tesla','amd','radeon','vega','intel','arc','iris','gpu','adapter','device','directml','dml','cuda','rocm','metal','mps')):
            try:
                self._gpu_debug.append(txt)
                if hasattr(self, 'device_value_label') and self.device_value_label is not None:
                    tips: list[str] = []
                    if self._device_backend:
                        tips.append(f"Backend: {self._device_backend}")
                    if self._device_model:
                        tips.append(f"Model: {self._device_model}")
                    tips.append("Samples:")
                    tips.extend(list(self._gpu_debug))
                    self.device_value_label.setToolTip("\n".join(tips))
            except Exception:
                pass
    def _select_chat_by_id(self, cid: str) -> None:
        """Select the list row corresponding to the given chat id."""
        try:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it and it.data(Qt.UserRole) == cid:
                    self.list.setCurrentRow(i)
                    return
        except Exception:
            pass
    def _start_download_model(self, model: str) -> None:
        title = 'Download Required'
        size_hint = None
        try:
            size_hint = self._cli.model_size_hint(model)
        except Exception:
            size_hint = None
        if size_hint:
            msg = (
                f'The selected model "{model}" is not downloaded.\n\n'
                f'Estimated size: {size_hint}.\n\n'
                'Do you want to proceed with the download?'
            )
        else:
            msg = (
                f'The selected model "{model}" is not downloaded.\n\n'
                'It will be fetched and may require additional disk space.\n\n'
                'Do you want to proceed with the download?'
            )
        try:
            resp = QMessageBox.question(self, title, msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        except Exception:
            resp = QMessageBox.No
        if resp != QMessageBox.Yes:
            return
        self._dl_model = model
        if size_hint:
            self._dl_size_str = size_hint
        try:
            dlg = QProgressDialog(self)
            dlg.setWindowTitle('Download in Progress...')
            dlg.setCancelButton(None)
            dlg.setRange(0, 0)
            dlg.setValue(0)
            dlg.setMinimumDuration(0)
            dlg.setWindowModality(Qt.ApplicationModal)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            label = f'Downloading {model}'
            if self._dl_size_str:
                label += f' ({self._dl_size_str})'
            dlg.setLabelText(label)
            try:
                dlg.setMinimumWidth(560)
            except Exception:
                pass
            try:
                lay = dlg.layout()
                if lay:
                    lay.setContentsMargins(12, 12, 12, 12)
                    lay.setSpacing(8)
            except Exception:
                pass
            try:
                bar = dlg.findChild(QProgressBar)
                if bar:
                    bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    bar.setMinimumHeight(18)
            except Exception:
                pass
            try:
                lbl = dlg.findChild(QLabel)
                if lbl:
                    lbl.setWordWrap(True)
                    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            except Exception:
                pass
            self._dl_dialog = dlg
        except Exception:
            self._dl_dialog = None
        # Start in indeterminate (busy) mode; switch to determinate when we detect percent/ratio
        self._dl_is_determinate = False
        self._dl_anim_value = 0
        self._dl_anim_dir = 1
        self._dl_bytes_done = None
        self._dl_bytes_total = None
        try:
            if self._dl_size_str:
                m = re.match(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB|KiB|MiB|GiB|TiB)", self._dl_size_str, re.IGNORECASE)
                if m:
                    unit = m.group(2).upper()
                    v = float(m.group(1))
                    mul = {"KB":1024.0, "MB":1024.0**2, "GB":1024.0**3, "TB":1024.0**4, "KIB":1024.0, "MIB":1024.0**2, "GIB":1024.0**3, "TIB":1024.0**4}
                    self._dl_bytes_total = v * mul.get(unit, 1.0)
        except Exception:
            pass
        def _runner() -> None:
            ok = self._cli.ensure_model_downloaded(model, on_output=lambda s: self._bridge.dl_line.emit(s))
            try:
                self._bridge.dl_done.emit(bool(ok))
            except Exception:
                pass
        t = threading.Thread(target=_runner, daemon=True)
        self._dl_thread = t
        try:
            t.start()
        except Exception:
            pass
        try:
            if self._dl_dialog is not None:
                self._dl_dialog.show()
        except Exception:
            pass
        try:
            if not self._dl_is_determinate and not self._dl_anim_timer.isActive():
                self._dl_anim_timer.start()
        except Exception:
            pass
    def _on_download_output(self, line: str) -> None:
        dlg = self._dl_dialog
        model = self._dl_model or ''
        if not dlg:
            return
        text = (line or '').strip()
        if not self._dl_size_str:
            try:
                m = re.search(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB|KiB|MiB|GiB|TiB)", text, re.IGNORECASE)
                if m:
                    self._dl_size_str = f"{m.group(1)} {m.group(2).upper()}"
            except Exception:
                pass
        try:
            pct = None
            mp = re.search(r"(\d{1,3})(?:\.\d+)?\s*%", text)
            if mp:
                try:
                    pct = max(0, min(100, int(float(mp.group(1)))))
                except Exception:
                    pct = None
            if pct is None:
                size_re = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(K|M|G|T|Ki|Mi|Gi|Ti)?(?:B(?!/s)|[Bb]ytes?)", re.IGNORECASE)
                vals: list[float] = []
                for m in size_re.finditer(text):
                    try:
                        num = m.group(1)
                        num = num.replace(',', '.')
                        v = float(num)
                    except Exception:
                        continue
                    unit = (m.group(2) or '').lower()
                    if unit in ('k', 'ki'):
                        v *= 1024.0
                    elif unit in ('m', 'mi'):
                        v *= 1024.0**2
                    elif unit in ('g', 'gi'):
                        v *= 1024.0**3
                    elif unit in ('t', 'ti'):
                        v *= 1024.0**4
                    vals.append(v)
                done_b = None
                total_b = None
                cand = None
                for i in range(len(vals) - 1):
                    if vals[i+1] >= vals[i]:
                        cand = (vals[i], vals[i+1])
                        break
                if not cand and len(vals) >= 2:
                    cand = (vals[-2], vals[-1])
                if cand:
                    done_b, total_b = cand
                elif len(vals) == 1 and self._dl_bytes_total:
                    done_b = vals[0]
                    total_b = self._dl_bytes_total
                if total_b and total_b > 0 and done_b is not None:
                    try:
                        pct = max(0, min(100, int((done_b / total_b) * 100)))
                        self._dl_bytes_done = done_b
                        self._dl_bytes_total = total_b
                    except Exception:
                        pct = None
                elif self._dl_size_str and self._dl_bytes_total is None:
                    try:
                        m2 = re.match(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB|KiB|MiB|GiB|TiB)", self._dl_size_str, re.IGNORECASE)
                        if m2:
                            unit = m2.group(2).upper()
                            v = float(m2.group(1))
                            mul = {"KB":1024.0, "MB":1024.0**2, "GB":1024.0**3, "TB":1024.0**4, "KIB":1024.0, "MIB":1024.0**2, "GIB":1024.0**3, "TIB":1024.0**4}
                            self._dl_bytes_total = v * mul.get(unit, 1.0)
                    except Exception:
                        pass
            if pct is not None:
                try:
                    if dlg.maximum() == 0:
                        dlg.setRange(0, 100)
                except Exception:
                    pass
                self._dl_is_determinate = True
                try:
                    if self._dl_anim_timer.isActive():
                        self._dl_anim_timer.stop()
                except Exception:
                    pass
                dlg.setValue(pct)
            label = f'Downloading {model}'
            if self._dl_bytes_done is not None and self._dl_bytes_total:
                def _fmt_bytes(b: float) -> str:
                    u = ['B', 'KB', 'MB', 'GB', 'TB']
                    v = float(b)
                    i = 0
                    while v >= 1024.0 and i < 4:
                        v /= 1024.0
                        i += 1
                    return f"{v:.1f} {u[i]}"
                try:
                    label += f" – {_fmt_bytes(self._dl_bytes_done)} / {_fmt_bytes(self._dl_bytes_total)}"
                except Exception:
                    pass
            elif self._dl_size_str:
                label += f' ({self._dl_size_str})'
            low = text.lower()
            if 'verifying' in low:
                label += ' – verifying…'
            elif 'extracting' in low:
                label += ' – extracting…'
            elif 'downloading' in low or 'fetching' in low:
                label += ' – downloading…'
            dlg.setLabelText(label)
        except Exception:
            pass
    def _on_download_done(self, ok: bool) -> None:
        try:
            if self._dl_dialog is not None:
                self._dl_dialog.close()
        except Exception:
            pass
        model = self._dl_model or ''
        self._dl_dialog = None
        self._dl_thread = None
        try:
            if self._dl_anim_timer.isActive():
                self._dl_anim_timer.stop()
        except Exception:
            pass
        self._dl_is_determinate = False
        self._dl_anim_value = 0
        self._dl_anim_dir = 1
        try:
            if ok:
                try:
                    storage.add_downloaded_model(model)
                except Exception:
                    pass
                try:
                    pairs = self._cli.list_cached_pairs()
                    storage.migrate_downloaded_aliases(pairs)
                except Exception:
                    pass
                try:
                    self._refresh_models()
                    self.model_combo.setCurrentText(model)
                except Exception:
                    pass
                try:
                    QMessageBox.information(self, 'Download Complete', f'Model "{model}" was downloaded successfully.')
                except Exception:
                    pass
            else:
                try:
                    QMessageBox.warning(self, 'Download Failed', f'Failed to download model "{model}".')
                except Exception:
                    pass
        finally:
            self._dl_size_str = None
            self._dl_model = None
    def _tick_download_anim(self) -> None:
        """Animate the download progress bar when no percentage is available."""
        dlg = self._dl_dialog
        if not dlg or self._dl_is_determinate:
            return
        try:
            if not (dlg.minimum() == 0 and dlg.maximum() == 0):
                dlg.setRange(0, 0)
        except Exception:
            pass
    def _on_delete_output(self, line: str) -> None:
        dlg = self._rm_dialog
        model = self._rm_model or ''
        if not dlg:
            return
        text = (line or '').strip()
        try:
            pct = None
            mp = re.search(r"(\d{1,3})%", text)
            if mp:
                pct = max(0, min(100, int(mp.group(1))))
            if pct is not None:
                try:
                    if dlg.maximum() == 0:
                        dlg.setRange(0, 100)
                except Exception:
                    pass
                dlg.setValue(pct)
            label = f'Deleting {model}'
            low = text.lower()
            if 'verifying' in low:
                label += ' – verifying…'
            elif 'removing' in low or 'deleting' in low:
                label += ' – removing…'
            elif 'cleaning' in low or 'purging' in low:
                label += ' – cleaning…'
            dlg.setLabelText(label)
        except Exception:
            pass
    def _on_delete_done(self, ok: bool) -> None:
        try:
            if self._rm_dialog is not None:
                self._rm_dialog.close()
        except Exception:
            pass
        name = self._rm_model or ''
        counterpart = self._rm_counterpart
        self._rm_dialog = None
        self._rm_thread = None
        try:
            if ok:
                try:
                    storage.remove_downloaded_model(name)
                    if counterpart and counterpart != name:
                        storage.remove_downloaded_model(counterpart)
                except Exception:
                    pass
                try:
                    self._refresh_models()
                except Exception:
                    pass
                try:
                    QMessageBox.information(self, 'Deletion Complete', f'Model "{name}" was successfully removed.')
                except Exception:
                    pass
            else:
                try:
                    QMessageBox.warning(self, 'Deletion Failed', f'Failed to remove "{name}" from cache.')
                except Exception:
                    pass
        finally:
            self._rm_model = None
            self._rm_counterpart = None
    def _on_entry_changed(self) -> None:
        active = bool(self.entry.toPlainText().strip())
        if hasattr(self, 'send_btn') and self.send_btn is not None:
            self.send_btn.setProperty('active', active)
            try:
                self.send_btn.setEnabled(active)
            except Exception:
                pass
            self.send_btn.style().unpolish(self.send_btn)
            self.send_btn.style().polish(self.send_btn)
        try:
            self._auto_resize_entry()
        except Exception:
            pass
    def _auto_resize_entry(self) -> None:
        """Auto-adjust the input height up to a cap based on content."""
        min_h = 36
        max_h = 160
        try:
            doc = self.entry.document()
            w = self.entry.viewport().width()
            if w > 0:
                doc.setTextWidth(w)
            h = int(doc.documentLayout().documentSize().height())
            new_h = max(min_h, min(max_h, h + 6))
            self.entry.setFixedHeight(new_h)
            if hasattr(self, 'send_btn') and self.send_btn is not None:
                try:
                    fm = self.entry.fontMetrics()
                    one_line_h = max(min_h, int(fm.lineSpacing() + 6))
                    btn_extra = 14
                    if not hasattr(self, '_send_btn_base_h') or self._send_btn_base_h is None:
                        self._send_btn_base_h = one_line_h + btn_extra
                    if new_h <= one_line_h + 2:
                        self._send_btn_base_h = one_line_h + btn_extra
                    btn_h = int(self._send_btn_base_h)
                    pad_px = 10
                    icon_side = max(12, int(btn_h*0.4))
                    self.send_btn.setFixedSize(btn_h, btn_h)
                    self.send_btn.setIconSize(QSize(icon_side, icon_side))
                    try:
                        self.send_btn.setStyleSheet(f"QToolButton#SendButton {{ border: 0px; border-radius: {btn_h//2}px; padding: {pad_px}px; }}")
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            self.entry.setFixedHeight(min_h)
            if hasattr(self, 'send_btn') and self.send_btn is not None:
                try:
                    fm = self.entry.fontMetrics() if hasattr(self.entry, 'fontMetrics') else None
                    one_line_h = max(min_h, int(fm.lineSpacing() + 6)) if fm else min_h
                    btn_extra = 14
                    if not hasattr(self, '_send_btn_base_h') or self._send_btn_base_h is None:
                        self._send_btn_base_h = one_line_h + btn_extra
                    btn_h = int(self._send_btn_base_h)
                    pad_px = 10
                    icon_side = max(12, int(btn_h*0.4))
                    self.send_btn.setFixedSize(btn_h, btn_h)
                    self.send_btn.setIconSize(QSize(icon_side, icon_side))
                except Exception:
                    pass

    # --- Send ---
    def _send(self) -> None:
        txt = self.entry.toPlainText().strip()
        if not txt:
            return
        # Derive model from combo box in case _on_model_changed didn't fire
        try:
            current_model = self.model_combo.currentText()
        except Exception:
            current_model = self._model
        if current_model and '─' not in (current_model or ''):
            self._model = current_model
        if not self._model:
            try:
                QMessageBox.warning(self, 'Select Model', 'Please select a model in the top toolbar before sending a message.')
            except Exception:
                pass
            return
        # Ensure there is a current chat; if none, create and select one now
        origin_cid = self._current_chat
        if origin_cid is None:
            try:
                origin_cid = storage.create_chat('New Chat')
            except Exception:
                origin_cid = None
            try:
                self._load_chats()
                if origin_cid is not None:
                    self._select_chat_by_id(origin_cid)
            except Exception:
                pass
            self._current_chat = origin_cid
            self._messages = []
            try:
                self.chat.reset_day_groups()
            except Exception:
                pass
        if origin_cid is None:
            return
        self.entry.clear()
        now_iso = datetime.now().isoformat()
        self.chat.add_message('user', txt, now_iso, animate=False)
        try:
            self.chat.force_scroll_bottom_deferred()
        except Exception:
            pass
        self._messages.append({'role':'user','content':txt,'ts':now_iso})
        storage.save_messages(origin_cid, self._messages)
        self._ensure_chat_started()
        # Debounce typing indicator (show if assistant not yet responded after 300ms)
        self._assistant_waiting = True
        try:
            self._inflight_queue.append(origin_cid)
        except Exception:
            pass
        try:
            self._waiting_by_chat[origin_cid] = int(self._waiting_by_chat.get(origin_cid, 0)) + 1
        except Exception:
            pass
        def _fire_typing() -> None:
            # Only show in the originating chat if still waiting and user is viewing it
            if int(self._waiting_by_chat.get(origin_cid, 0)) <= 0:
                return
            if self._current_chat != origin_cid:
                return
            # Force initial snap-to-bottom when typing indicator appears
            sticky = True
            try:
                self.chat.show_typing(sticky=sticky)
            except Exception:
                pass
            def _scroll_after_typing() -> None:
                try:
                    # Lightweight follow-up: try to keep in view if user remained at bottom
                    if bool(self.chat.is_at_bottom()):
                        self.chat.scroll_to_bottom()
                except Exception:
                    pass
            try:
                QTimer.singleShot(0, _scroll_after_typing)
                QTimer.singleShot(16, _scroll_after_typing)
                QTimer.singleShot(100, _scroll_after_typing)
            except Exception:
                pass
        try:
            if getattr(self, '_typing_fire_slot', None) is not None:
                try:
                    self._typing_debounce.timeout.disconnect(self._typing_fire_slot)
                except Exception:
                    pass
        except Exception:
            pass
        self._typing_fire_slot = _fire_typing
        self._typing_debounce.timeout.connect(_fire_typing)
        try:
            self._typing_debounce.start(300)
        except Exception:
            pass
        try:
            self._cli.send_prompt(txt)
        except Exception:
            pass
    def _ensure_chat_started(self) -> None:
        if self._chat_started or not self._model:
            return
        # Ensure model is present (best effort)
        try:
            self._cli.ensure_model_downloaded(self._model)
        except Exception:
            pass
        try:
            self._cli.start_chat(self._model, on_raw_output=lambda s: self._bridge.raw.emit(s), on_assistant=lambda s: self._bridge.assistant.emit(s))
            self._chat_started = True
        except Exception:
            self._chat_started = False
    def _apply_theme(self, theme: dict) -> None:
        qss = styles.set_theme(theme)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(qss)
    
    def _on_chat_show_role_changed(self, v: bool) -> None:
        try:
            self.chat.set_show_role(bool(v))
        except Exception:
            pass
        try:
            storage.set_bool('chat_show_role', bool(v))
        except Exception:
            pass
    
    def _on_chat_show_timestamp_changed(self, v: bool) -> None:
        try:
            self.chat.set_show_timestamp(bool(v))
        except Exception:
            pass
        try:
            storage.set_bool('chat_show_timestamp', bool(v))
        except Exception:
            pass
    
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, initial_theme=styles.get_theme())
        dlg.themeChanged.connect(self._apply_theme)
        try:
            dlg.chatShowRoleChanged.connect(self._on_chat_show_role_changed)
            dlg.chatShowTimestampChanged.connect(self._on_chat_show_timestamp_changed)
        except Exception:
            pass
        dlg.exec()
    
    def _on_assistant(self, text: str) -> None:
        """Animate assistant reply with typing effect and save on completion."""
        # Determine originating chat for this reply
        try:
            cid = self._inflight_queue.popleft()
        except Exception:
            cid = self._current_chat
        if cid is None:
            return
        # Clear waiting refcount for that chat (decrement)
        remaining = 0
        try:
            if cid in self._waiting_by_chat:
                self._waiting_by_chat[cid] = max(0, int(self._waiting_by_chat.get(cid, 0)) - 1)
                remaining = int(self._waiting_by_chat.get(cid, 0))
                if self._waiting_by_chat[cid] <= 0:
                    self._waiting_by_chat.pop(cid, None)
        except Exception:
            remaining = 0
        full = (text or '').strip()
        now_iso = datetime.now().isoformat()
        # If the reply is for the currently open chat, animate it in UI
        if self._current_chat == cid:
            # Always remove typing indicator before rendering assistant reply
            self._assistant_waiting = False
            try:
                self.chat.hide_typing()
            except Exception:
                pass
            sticky = False
            try:
                sticky = bool(self.chat.is_at_bottom())
            except Exception:
                sticky = False
            bubble = self.chat.add_message('assistant', '', now_iso, animate=False)
            # Ensure the new assistant bubble is brought into view immediately
            try:
                self.chat.force_scroll_bottom_deferred()
            except Exception:
                pass
            if self._typing and isinstance(self._typing, dict):
                try:
                    tmr = self._typing.get('timer')
                    if tmr:
                        tmr.stop()
                except Exception:
                    pass
                self._typing = None
            timer = QTimer(self)
            try:
                timer.setInterval(16)
            except Exception:
                pass
            state = {'timer': timer, 'bubble': bubble, 'text': full, 'index': 0, 'iso': now_iso, 'sticky': sticky}
            def _tick() -> None:
                idx = state['index']
                s = state['text']
                # Speed up typing for longer messages while keeping it readable
                step = max(3, int(len(s) // 120) or 3)
                if idx >= len(s):
                    try:
                        state['timer'].stop()
                    except Exception:
                        pass
                    if self._current_chat is not None:
                        try:
                            self._messages.append({'role':'assistant','content':s,'ts':state['iso']})
                            storage.save_messages(self._current_chat, self._messages)
                        except Exception:
                            pass
                    # Unconditional final scroll to bottom after AI message completes
                    def _scroll_after_ai_done() -> None:
                        try:
                            self.chat.scroll_to_bottom()
                        except Exception:
                            pass
                    try:
                        QTimer.singleShot(0, _scroll_after_ai_done)
                        QTimer.singleShot(16, _scroll_after_ai_done)
                        QTimer.singleShot(100, _scroll_after_ai_done)
                    except Exception:
                        pass
                    self._typing = None
                    return
                nxt = min(len(s), idx + step)
                try:
                    state['bubble'].append_text(s[idx:nxt])
                except Exception:
                    pass
                state['index'] = nxt
                try:
                    if bool(self.chat.is_at_bottom()):
                        self.chat.scroll_to_bottom()
                except Exception:
                    pass
            # Keep lightweight periodic bottom sync during early layout settles
            def _scroll_new_assistant() -> None:
                try:
                    self.chat.scroll_to_bottom()
                except Exception:
                    pass
            try:
                QTimer.singleShot(0, _scroll_new_assistant)
                QTimer.singleShot(16, _scroll_new_assistant)
            except Exception:
                pass
            timer.timeout.connect(_tick)
            self._typing = state
            timer.start()
        else:
            # Different chat: persist directly to that chat's storage
            try:
                data = storage.load_chat(cid) or {}
                msgs = list(data.get('messages', []))
                msgs.append({'role':'assistant','content':full,'ts':now_iso})
                storage.save_messages(cid, msgs)
            except Exception:
                pass
