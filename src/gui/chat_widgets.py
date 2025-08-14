from datetime import datetime
from PySide6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QSizePolicy, QGraphicsDropShadowEffect
from .styles import BUBBLE_USER, BUBBLE_AI, TEXT, SUBTEXT, FONT_CHAT, FONT_TS, FONT_SENDER, USER_TEXT

class Bubble(QFrame):
    """Rounded message bubble with optional alignment and timestamp."""
    def __init__(self, text: str, is_user: bool, timestamp: str) -> None:
        super().__init__()
        self._text = text
        self._is_user = is_user
        self._timestamp = timestamp
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setObjectName('Bubble')
        if is_user:
            style = "QFrame#Bubble{background:%s;border:none;border-radius:12px;} QLabel#Msg{color:%s; font-size:16px; background: transparent;} QLabel#Ts{color:%s; font-size:16px; background: transparent;} QLabel#Sender{background: transparent;}" % (
                BUBBLE_USER,
                USER_TEXT,
                SUBTEXT,
            )
        else:
            style = "QFrame#Bubble{background:%s;border:none;border-radius:12px;} QLabel#Msg{color:%s; font-size:16px; background: transparent;} QLabel#Ts{color:%s; font-size:16px; background: transparent;} QLabel#Sender{background: transparent;}" % (
                BUBBLE_AI,
                TEXT,
                SUBTEXT,
            )
        self.setStyleSheet(style)
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
        # Header row with sender label only (no avatar images)
        header = QHBoxLayout()
        header.setContentsMargins(0,0,0,0)
        header.setSpacing(8)
        header.addWidget(sender, 0)
        # Timestamp next to sender, flush right
        ts = QLabel(timestamp)
        ts.setFont(FONT_TS)
        ts.setObjectName('Ts')
        header.addWidget(ts, 0)
        header.addStretch(1)
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setFont(FONT_CHAT)
        msg.setObjectName('Msg')
        lay.addLayout(header)
        lay.addWidget(msg)
        # No outline/shadow on bubbles
        self.setGraphicsEffect(None)
    # Use default sizeHint from QFrame to allow height to fit content

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
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._v.addWidget(spacer)
    def reset_day_groups(self) -> None:
        """Reset internal grouping so next message will insert a new date separator."""
        self._last_date_key = None
    def _fmt_date(self, dt: datetime) -> str:
        """Format a date like 'Aug. 12, 2025'."""
        month = dt.strftime('%b') + '.'
        return f"{month} {dt.day}, {dt.year}"
    def _fmt_time(self, dt: datetime) -> str:
        """Format a time like '01:50:45 AM'."""
        return dt.strftime('%I:%M:%S %p')
    def add_message(self, role: str, text: str, iso_ts: str) -> None:
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
        line = QHBoxLayout()
        line.setContentsMargins(0,0,0,0)
        line.setSpacing(6)
        if is_user:
            line.addStretch(1)
            line.addWidget(bubble, 0)
        else:
            line.addWidget(bubble, 0)
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
