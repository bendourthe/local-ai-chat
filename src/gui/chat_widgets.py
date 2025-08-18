from datetime import datetime
import os
from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QPen, QFontMetrics
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QSizePolicy, QGraphicsDropShadowEffect
from .styles import FONT_CHAT, FONT_TS, FONT_SENDER

class Bubble(QFrame):
    """Rounded message bubble with optional alignment and timestamp."""
    def __init__(self, text: str, is_user: bool, timestamp: str) -> None:
        super().__init__()
        self._text = text
        self._is_user = is_user
        self._timestamp = timestamp
        # Prefer natural content width; don't stretch across the row
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setObjectName('Bubble')
        self.setProperty('sender', 'user' if is_user else 'ai')
        try:
            self.style().unpolish(self); self.style().polish(self); self.update()
        except Exception:
            pass
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12,8,12,8)
        lay.setSpacing(4)
        sender = QLabel('YOU' if is_user else 'AI')
        f = FONT_SENDER
        f.setCapitalization(QFont.AllUppercase)
        try:
            f.setLetterSpacing(QFont.PercentageSpacing, 105)
        except Exception:
            pass
        sender.setFont(f)
        sender.setStyleSheet('font-size:16px;')
        sender.setObjectName('Sender')
        self._sender_label = sender
        # Header row with sender label and timestamp
        header = QHBoxLayout()
        header.setContentsMargins(0,0,0,0)
        header.setSpacing(8)
        header.addWidget(sender, 0)
        # Timestamp immediately to the right of sender
        ts = QLabel(timestamp)
        ts.setFont(FONT_TS)
        ts.setObjectName('Ts')
        header.addWidget(ts, 0)
        header.addStretch(1)
        self._ts_label = ts
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setFont(FONT_CHAT)
        msg.setObjectName('Msg')
        self._msg_label = msg
        lay.addLayout(header)
        lay.addWidget(msg)
        # No outline/shadow on bubbles
        self.setGraphicsEffect(None)
        # Track preferred width and last bounds
        self._desired_width: int | None = None
        self._last_bounds: tuple[int, int] = (0, 0)
        # Visibility flags (default True)
        self._show_role = True
        self._show_ts = True
    def _natural_content_width(self) -> int:
        """Return width in pixels of the longer of header or single-line message, including bubble padding."""
        try:
            pad = 24
            spc = 8
            fm_sender = QFontMetrics(self._sender_label.font())
            fm_ts = QFontMetrics(self._ts_label.font())
            w_sender = fm_sender.horizontalAdvance(self._sender_label.text()) if self._sender_label.isVisible() else 0
            w_ts = fm_ts.horizontalAdvance(self._ts_label.text()) if self._ts_label.isVisible() else 0
            w_header = w_sender + (spc if (w_sender and w_ts) else 0) + w_ts + pad
            fm_msg = QFontMetrics(self._msg_label.font())
            txt = (self._msg_label.text() or '').replace('\n', ' ')
            w_msg = fm_msg.horizontalAdvance(txt) + pad
            return max(w_header, w_msg)
        except Exception:
            return 260
    def apply_width(self, min_w: int, max_w: int) -> None:
        """Apply min/max width to the bubble and label so text wraps only past max and bubble never shrinks below min."""
        try:
            self._last_bounds = (min_w, max_w)
            if max_w and max_w > 0:
                self.setMaximumWidth(max_w)
                inner_max = max(80, max_w - 24)
                try:
                    self._msg_label.setMaximumWidth(inner_max)
                except Exception:
                    pass
            nat = self._natural_content_width()
            # Preferred width is the natural width clamped to max_w and not below min_w
            pref = nat
            if max_w and max_w > 0:
                pref = min(pref, max_w)
            if min_w and min_w > 0:
                pref = max(pref, min_w)
            self._desired_width = int(pref)
            try:
                # Keep minimum small so layout can shrink if needed; rely on sizeHint to prefer pref
                self.setMinimumWidth(0 if not (min_w and min_w > 0) else min_w)
            except Exception:
                pass
            try:
                self._msg_label.setMinimumWidth(0)
            except Exception:
                pass
            try:
                self.updateGeometry()
            except Exception:
                pass
        except Exception:
            pass
    def sizeHint(self) -> QSize:
        """Prefer the computed desired width while letting height be determined by layout."""
        try:
            base = super().sizeHint()
        except Exception:
            base = QSize(200, 100)
        w = self._desired_width if isinstance(self._desired_width, int) and self._desired_width > 0 else base.width()
        return QSize(int(w), base.height())
    # Use default sizeHint from QFrame to allow height to fit content
    def set_text(self, text: str) -> None:
        """Set message text content."""
        self._msg_label.setText(text)
        try:
            mn, mx = self._last_bounds
            self.apply_width(mn, mx)
        except Exception:
            pass
    def append_text(self, s: str) -> None:
        """Append to message text content."""
        self._msg_label.setText(self._msg_label.text() + s)
        try:
            mn, mx = self._last_bounds
            self.apply_width(mn, mx)
        except Exception:
            pass
    def text(self) -> str:
        """Return current message text."""
        return self._msg_label.text()
    def set_show_role(self, v: bool) -> None:
        """Show or hide the sender label."""
        self._show_role = bool(v)
        try:
            self._sender_label.setVisible(self._show_role)
        except Exception:
            pass
        try:
            mn, mx = self._last_bounds
            self.apply_width(mn, mx)
        except Exception:
            pass
    def set_show_timestamp(self, v: bool) -> None:
        """Show or hide the timestamp label."""
        self._show_ts = bool(v)
        try:
            self._ts_label.setVisible(self._show_ts)
        except Exception:
            pass
        try:
            mn, mx = self._last_bounds
            self.apply_width(mn, mx)
        except Exception:
            pass

class ChatView(QScrollArea):
    """Scrollable chat view that stacks Bubble widgets left/right."""
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName('ChatView')
        self.setWidgetResizable(True)
        # Ensure QSS backgrounds apply to the scroll area and its viewport
        self.setAttribute(Qt.WA_StyledBackground, True)
        try:
            self.viewport().setAttribute(Qt.WA_StyledBackground, True)
        except Exception:
            pass
        self._wrap = QWidget()
        self.setWidget(self._wrap)
        self._v = QVBoxLayout(self._wrap)
        # Add left/right gutters so AI bubbles don't touch the left edge and user bubbles don't touch the scrollbar
        self._v.setContentsMargins(16,16,16,16)
        self._v.setSpacing(10)
        self._last_date_key = None
        # Typing indicator state
        self._typing_cont = None
        self._typing_bubble = None
        self._typing_timer: QTimer | None = None
        self._typing_step = 0
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._v.addWidget(spacer)
        # Chat-level visibility flags (default True)
        self._show_role = True
        self._show_ts = True
    def reset_day_groups(self) -> None:
        """Reset internal grouping so next message will insert a new date separator."""
        self._last_date_key = None
    def _fmt_date(self, dt: datetime) -> str:
        """Format a date like 'Aug. 12, 2025'."""
        month = dt.strftime('%b') + '.'
        return f"{month} {dt.day}, {dt.year}"
    def _fmt_time(self, dt: datetime) -> str:
        """Format time like '01:50:45 AM'."""
        return dt.strftime('%I:%M:%S %p')
    def add_message(self, role: str, text: str, iso_ts: str):
        # Determine sender side
        is_user = role.lower().startswith('user') or role == 'YOU' or role == 'user'
        # Parse ISO timestamp and manage date separators
        try:
            dt = datetime.fromisoformat(iso_ts) if iso_ts else datetime.now()
        except Exception:
            dt = datetime.now()
        date_key = dt.strftime('%Y-%m-%d')
        if self._last_date_key != date_key:
            self._last_date_key = date_key
            sep = QLabel(self._fmt_date(dt))
            sep.setObjectName('DateSep')
            sep.setAlignment(Qt.AlignCenter)
            self._v.insertWidget(self._v.count()-1, sep)
        # Build bubble with time-only in header
        bubble = Bubble(text, is_user, self._fmt_time(dt))
        try:
            bubble.set_show_role(bool(self._show_role))
            bubble.set_show_timestamp(bool(self._show_ts))
        except Exception:
            pass
        # Apply initial min/max width based on viewport
        try:
            mn, mx = self._bubble_widths()
            bubble.apply_width(mn, mx)
        except Exception:
            pass
        line = QHBoxLayout()
        line.setContentsMargins(0,0,0,0)
        line.setSpacing(6)
        if is_user:
            # Right-aligned: spacer on the left
            line.addStretch(1)
            line.addWidget(bubble)
        else:
            # Left-aligned: spacer on the right
            line.addWidget(bubble)
            line.addStretch(1)
        cont = QFrame()
        cont.setLayout(line)
        self._v.insertWidget(self._v.count()-1, cont)
        # Smooth scroll to bottom
        sb = self.verticalScrollBar()
        anim = QPropertyAnimation(sb, b"value", self)
        anim.setDuration(150)
        anim.setStartValue(sb.value())
        anim.setEndValue(sb.maximum())
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start()
        return bubble
    def _bubble_widths(self) -> tuple[int, int]:
        """Compute (min_w, max_w) based on current viewport size: min 0, max 75% of chat area width."""
        try:
            vw = self.viewport().width()
        except Exception:
            vw = 800
        # Clamp to sensible pixel bounds for max only
        max_w = max(240, int(vw * 0.75))
        min_w = 0
        return (min_w, max_w)
    def _apply_bubble_widths(self) -> None:
        """Apply current max width to all bubbles (call on resize)."""
        mn, mx = self._bubble_widths()
        try:
            for i in range(self._v.count()):
                it = self._v.itemAt(i)
                w = it.widget() if it is not None else None
                if not isinstance(w, QFrame):
                    continue
                lay = w.layout()
                if not isinstance(lay, QHBoxLayout):
                    continue
                for j in range(lay.count()):
                    cw = lay.itemAt(j).widget()
                    if isinstance(cw, Bubble):
                        cw.apply_width(mn, mx)
                        break
        except Exception:
            pass
    def resizeEvent(self, e) -> None:
        try:
            super().resizeEvent(e)
        except Exception:
            pass
        self._apply_bubble_widths()
    def is_at_bottom(self) -> bool:
        """Return True if the view is scrolled to bottom."""
        sb = self.verticalScrollBar()
        return int(sb.value()) >= int(sb.maximum()) - 2
    def scroll_to_bottom(self) -> None:
        """Scroll the view to the bottom."""
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
    def set_show_role(self, v: bool) -> None:
        """Set whether bubbles show the sender label; updates existing bubbles."""
        self._show_role = bool(v)
        try:
            for i in range(self._v.count()):
                it = self._v.itemAt(i)
                w = it.widget() if it is not None else None
                if not isinstance(w, QFrame):
                    continue
                lay = w.layout()
                if not isinstance(lay, QHBoxLayout):
                    continue
                for j in range(lay.count()):
                    cw = lay.itemAt(j).widget()
                    if isinstance(cw, Bubble):
                        cw.set_show_role(self._show_role)
                        break
        except Exception:
            pass
        self._apply_bubble_widths()
    def set_show_timestamp(self, v: bool) -> None:
        """Set whether bubbles show the timestamp label; updates existing bubbles."""
        self._show_ts = bool(v)
        try:
            for i in range(self._v.count()):
                it = self._v.itemAt(i)
                w = it.widget() if it is not None else None
                if not isinstance(w, QFrame):
                    continue
                lay = w.layout()
                if not isinstance(lay, QHBoxLayout):
                    continue
                for j in range(lay.count()):
                    cw = lay.itemAt(j).widget()
                    if isinstance(cw, Bubble):
                        cw.set_show_timestamp(self._show_ts)
                        break
        except Exception:
            pass
        self._apply_bubble_widths()
    def show_typing(self, sticky: bool = True) -> None:
        """Show a three-dot typing indicator aligned as an AI bubble."""
        # If already visible, just restart animation
        if self._typing_cont is not None and self._typing_bubble is not None:
            if self._typing_timer is not None:
                try:
                    self._typing_timer.stop()
                except Exception:
                    pass
            self._typing_step = 0
        else:
            # Build a minimal AI bubble and insert it
            dt = datetime.now()
            bubble = Bubble('', False, self._fmt_time(dt))
            try:
                bubble.set_show_role(bool(self._show_role))
                bubble.set_show_timestamp(bool(self._show_ts))
            except Exception:
                pass
            try:
                mn, mx = self._bubble_widths()
                bubble.apply_width(mn, mx)
            except Exception:
                pass
            line = QHBoxLayout()
            line.setContentsMargins(0,0,0,0)
            line.setSpacing(6)
            line.addWidget(bubble)
            line.addStretch(1)
            cont = QFrame()
            cont.setLayout(line)
            try:
                bubble.setAccessibleName('Assistant is typing')
                cont.setAccessibleName('Assistant is typing')
            except Exception:
                pass
            self._v.insertWidget(self._v.count()-1, cont)
            self._typing_cont = cont
            self._typing_bubble = bubble
        # Animate dots
        def _tick() -> None:
            self._typing_step = (self._typing_step + 1) % 4
            dots = '•' * (self._typing_step or 1)
            try:
                if self._typing_bubble is not None:
                    self._typing_bubble.set_text(dots)
            except Exception:
                pass
            if sticky:
                try:
                    self.scroll_to_bottom()
                except Exception:
                    pass
        # Reduced motion: disable animation if env var requests it
        rm = os.environ.get('LOCAL_CHAT_REDUCE_MOTION', '')
        reduce_motion = isinstance(rm, str) and rm.strip().lower() in ('1','true','yes','on')
        if reduce_motion:
            try:
                if self._typing_bubble is not None:
                    self._typing_bubble.set_text('…')
            except Exception:
                pass
            return
        if self._typing_timer is None:
            self._typing_timer = QTimer(self)
            self._typing_timer.setInterval(350)
            self._typing_timer.timeout.connect(_tick)
        else:
            try:
                self._typing_timer.timeout.disconnect()
            except Exception:
                pass
            self._typing_timer.timeout.connect(_tick)
        self._typing_timer.start()
        # Smooth scroll to bottom when first shown
        if sticky:
            sb = self.verticalScrollBar()
            anim = QPropertyAnimation(sb, b"value", self)
            anim.setDuration(150)
            anim.setStartValue(sb.value())
            anim.setEndValue(sb.maximum())
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            anim.start()
    def hide_typing(self) -> None:
        """Hide the typing indicator if present."""
        if self._typing_timer is not None:
            try:
                self._typing_timer.stop()
            except Exception:
                pass
        self._typing_timer = None
        self._typing_step = 0
        if self._typing_cont is not None:
            # Remove from layout safely
            try:
                for i in range(self._v.count()):
                    it = self._v.itemAt(i)
                    w = it.widget() if it is not None else None
                    if w is self._typing_cont:
                        self._v.removeWidget(self._typing_cont)
                        break
                self._typing_cont.setParent(None)
                self._typing_cont.deleteLater()
            except Exception:
                pass
        self._typing_cont = None
        self._typing_bubble = None

