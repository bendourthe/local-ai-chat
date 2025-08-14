from datetime import datetime
from typing import List, Dict, Optional
from PySide6.QtCore import Qt, QObject, Signal, QSize, QEvent, QPoint, QRect
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QListWidget, QListWidgetItem, QToolBar, QComboBox, QPushButton, QLineEdit, QTextEdit, QToolButton, QStyle, QGraphicsDropShadowEffect, QSizePolicy, QMenu, QInputDialog, QStackedLayout, QStyleOption, QStyleOptionFrame, QProxyStyle, QAbstractItemView, QMessageBox, QScrollBar
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

class MainWindow(QMainWindow):
    """Qt main window replicating the app with modern layout/colors."""
    def __init__(self) -> None:
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
        self._bridge = _Bridge()
        self._bridge.assistant.connect(self._on_assistant)
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
        # Data
        self._load_chats()
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
                btn.pressed.connect(lambda it=it: self.list.setCurrentItem(it))
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
        data = storage.load_chat(cid)
        if not data:
            return
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
            self.chat.add_message(role, txt, iso)
        self.chat._v.setEnabled(True)
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
        self._load_chats()
    # --- Models ---
    def _refresh_models(self) -> None:
        names = self._cli.list_models() or []
        downloaded = storage.get_downloaded_models()
        available = [n for n in names if n not in set(downloaded)]
        self.model_combo.clear()
        # Only show separator if both groups exist
        if downloaded and available:
            self.model_combo.addItems(downloaded)
            self.model_combo.addItem('────────────')
            self.model_combo.addItems(available)
        elif downloaded:
            self.model_combo.addItems(downloaded)
        elif available:
            self.model_combo.addItems(available)
        else:
            # Nothing to show; use placeholder when supported
            try:
                self.model_combo.setPlaceholderText('No models found')
                self.model_combo.setCurrentIndex(-1)
            except Exception:
                self.model_combo.addItem('No models found')
        # preselect first downloaded if any
        if downloaded:
            self.model_combo.setCurrentText(downloaded[0])
    def _delete_model(self) -> None:
        name = self.model_combo.currentText()
        if not name or '─' in name:
            return
        self._cli.remove_cached_model(name)
        self._refresh_models()
    def _on_model_changed(self, s: str) -> None:
        if not s or '─' in s:
            self._model = None
            return
        self._model = s
        # stop any running chat on model change
        try:
            self._cli.stop_chat()
        except Exception:
            pass
        self._chat_started = False
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
        if not txt or not self._current_chat:
            return
        self.entry.clear()
        now_iso = datetime.now().isoformat()
        self.chat.add_message('user', txt, now_iso)
        self._messages.append({'role':'user','content':txt,'ts':now_iso})
        storage.save_messages(self._current_chat, self._messages)
        self._ensure_chat_started()
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
            self._cli.start_chat(self._model, on_assistant=lambda s: self._bridge.assistant.emit(s))
            self._chat_started = True
        except Exception:
            self._chat_started = False
    def _apply_theme(self, theme: dict) -> None:
        qss = styles.set_theme(theme)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(qss)
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, initial_theme=styles.get_theme())
        dlg.themeChanged.connect(self._apply_theme)
        dlg.exec()
    def _on_assistant(self, text: str) -> None:
        # Append assistant message to UI and storage
        now_iso = datetime.now().isoformat()
        self.chat.add_message('assistant', text.strip(), now_iso)
        if self._current_chat is not None:
            self._messages.append({'role':'assistant','content':text.strip(),'ts':now_iso})
            storage.save_messages(self._current_chat, self._messages)

