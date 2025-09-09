# Color and style constants for the Qt UI (inspired by the provided mockup)
import json
import re
from pathlib import Path
from typing import Dict, Optional
from PySide6.QtGui import QFont

# Theme loading (minimal schema)
DEFAULT_THEME = {
    # Main app
    "APP_BG": "#2d3748",
    # App top bar
    "TOPBAR_BG": "#1d242f",
    "MODEL_BG": "#2a3446",
    # Chat history
    "SIDEBAR_BG": "#212938",
    "CHAT_LIST_BG": "#2d3748",
    "CHAT_LIST_ITEM_SELECTED_BG": "#2b3a55",
    # Chat area
    "CHAT_OUTER_BG": "#212938",
    "CHAT_INNER_BG": "#212938",
    "BUBBLE_USER": "#183161",
    "BUBBLE_AI": "#0F2347",
    # Typing area
    "TYPING_BAR_BG": "#2d3748",
    "TYPING_BAR_OUTLINE": "#2d3748",
    "TYPING_AREA_BG": "#212938",
    # Buttons
    "NEWCHAT_BUTTON_BG": "#102A5A",
    "DELETE_BUTTON_BG": "#8B1E1C",
    "SEND_BG": "#23488F",
    # Text
    "TEXT_PRIMARY": "#FFFFFF",
    "TEXT_MUTED": "#8B949E",
    # Misc
    "BORDER": "#132242"
}

# Sections used to organize theme.json when saving and for SettingsDialog grouping
SECTION_DEFS = {
    "main_app": ["APP_BG","BORDER"],
    "app_top_bar": ["TOPBAR_BG","MODEL_BG"],
    "chat_history": ["SIDEBAR_BG","CHAT_LIST_BG","CHAT_LIST_ITEM_SELECTED_BG"],
    "chat_area": ["CHAT_OUTER_BG","CHAT_INNER_BG","BUBBLE_USER","BUBBLE_AI"],
    "typing_area": ["TYPING_BAR_BG","TYPING_BAR_OUTLINE","TYPING_AREA_BG"],
    "buttons": ["NEWCHAT_BUTTON_BG","DELETE_BUTTON_BG","SEND_BG"],
    "text": ["TEXT_PRIMARY","TEXT_MUTED"],
}

# ---- Live theme helpers ----
def regenerate_qss(theme: Dict[str, str]) -> str:
    """Build a QSS string from the provided theme dict, deriving hover/pressed variants automatically."""
    def _clamp(v: int) -> int:
        return max(0, min(255, v))
    def _hex_to_rgb(h: str) -> tuple:
        s = h.strip().lstrip('#')
        if len(s) == 3:
            s = ''.join(c*2 for c in s)
        try:
            return (int(s[0:2],16), int(s[2:4],16), int(s[4:6],16))
        except Exception:
            return (0,0,0)
    def _rgb_to_hex(rgb: tuple) -> str:
        r,g,b = rgb
        return f"#{_clamp(r):02x}{_clamp(g):02x}{_clamp(b):02x}"
    def lighten(hex_color: str, amount: float) -> str:
        r,g,b = _hex_to_rgb(hex_color)
        if amount >= 0:
            r = r + (255-r)*amount; g = g + (255-g)*amount; b = b + (255-b)*amount
        else:
            a = -amount; r = r*(1-a); g = g*(1-a); b = b*(1-a)
        return _rgb_to_hex((int(r),int(g),int(b)))
    base = dict(THEME_DEFAULT or DEFAULT_THEME)
    if theme:
        base.update({k: str(v) for k, v in theme.items()})
    t = _apply_theme_aliases(base)
    # Derived
    model_hover = lighten(t['MODEL_BG'], 0.08)
    model_pressed = lighten(t['MODEL_BG'], 0.16)
    chat_item_hover = lighten(t['CHAT_LIST_BG'], 0.10)
    newchat_hover = lighten(t['NEWCHAT_BUTTON_BG'], 0.10)
    delete_hover = lighten(t['DELETE_BUTTON_BG'], 0.10)
    send_hover = lighten(t['SEND_BG'], 0.10)
    send_active = lighten(t['SEND_BG'], -0.06)
    send_icon_bg = lighten(t['SEND_BG'], -0.10)
    send_icon_hover = lighten(send_icon_bg, 0.10)
    mapping = {
        'TEXT_PRIMARY': t['TEXT_PRIMARY'],
        'TEXT_MUTED': t['TEXT_MUTED'],
        'FONT_FAMILY': FONT_FAMILY,
        'APP_BG': t['APP_BG'],
        'SIDEBAR_BG': t['SIDEBAR_BG'],
        'TOPBAR_BG': t['TOPBAR_BG'],
        'CHAT_OUTER_BG': t['CHAT_OUTER_BG'],
        'CHAT_INNER_BG': t['CHAT_INNER_BG'],
        'BORDER': t.get('BORDER', '#132242'),
        'TYPING_BAR_BG': t['TYPING_BAR_BG'],
        'TYPING_BAR_OUTLINE': t['TYPING_BAR_OUTLINE'],
        'TYPING_AREA_BG': t['TYPING_AREA_BG'],
        'MODEL_BG': t['MODEL_BG'],
        'MODEL_HOVER_BG': model_hover,
        'MODEL_PRESSED_BG': model_pressed,
        'CHAT_LIST_BG': t['CHAT_LIST_BG'],
        'CHAT_LIST_ITEM_HOVER_BG': chat_item_hover,
        'CHAT_LIST_ITEM_SELECTED_BG': t['CHAT_LIST_ITEM_SELECTED_BG'],
        'NEWCHAT_BUTTON_BG': t['NEWCHAT_BUTTON_BG'],
        'NEWCHAT_BUTTON_HOVER_BG': newchat_hover,
        'DELETE_BUTTON_BG': t['DELETE_BUTTON_BG'],
        'DELETE_BUTTON_HOVER_BG': delete_hover,
        'SEND_BG': t['SEND_BG'],
        'SEND_HOVER': send_hover,
        'SEND_ACTIVE': send_active,
        'SEND_ICON_BG': send_icon_bg,
        'SEND_ICON_HOVER_BG': send_icon_hover,
        'BUBBLE_USER': t['BUBBLE_USER'],
        'BUBBLE_AI': t['BUBBLE_AI'],
        'USER_TEXT': TEXT_PRIMARY,  # user text uses primary by default
        'CHEVRON_SVG_PATH': CHEVRON_SVG_PATH,
        'CHEVRON_UP_SVG_PATH': CHEVRON_UP_SVG_PATH,
        'CHEVRON_DOWN_SMALL_SVG_PATH': CHEVRON_DOWN_SMALL_SVG_PATH,
        'CHEVRON_UP_SMALL_SVG_PATH': CHEVRON_UP_SMALL_SVG_PATH,
    }
    return QSS_TEMPLATE % mapping

def get_theme() -> Dict[str, str]:
    """Return a copy of the current theme dict."""
    return dict(THEME)

def get_default_theme() -> Dict[str, str]:
    """Return a copy of the default theme (from file if present, else built-in)."""
    return dict(THEME_DEFAULT or DEFAULT_THEME)

def read_saved_current() -> Optional[Dict[str, str]]:
    """Read the saved 'current' theme from theme.json without altering globals.

    Returns:
        - dict: Flattened current theme if file is present
        - None: If theme.json is missing or malformed
    """
    try:
        p = Path(__file__).with_name('theme.json')
        if not p.exists():
            return None
        raw = p.read_text(encoding='utf-8')
        no_block = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
        no_line = re.sub(r"(^|\s)//.*$", "", no_block, flags=re.M)
        data = json.loads(no_line)
        if isinstance(data, dict) and ("current" in data or "default" in data):
            return _flatten_theme(data.get("current", {}))
        if isinstance(data, dict):
            # Legacy flat structure
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return None
    return None

def _rebind_constants() -> None:
    """Rebind exported module constants from THEME for code paths that still use them."""
    global APP_BG, SIDEBAR_BG, TOPBAR_BG, CHAT_OUTER_BG, CHAT_INNER_BG, CHAT_BG, BORDER
    global BUBBLE_USER, BUBBLE_AI
    global TYPING_BAR_BG, TYPING_BAR_OUTLINE, TYPING_AREA_BG
    global MODEL_BG
    global TEXT_PRIMARY, TEXT_MUTED, TEXT, SUBTEXT, USER_TEXT
    APP_BG = THEME["APP_BG"]
    SIDEBAR_BG = THEME["SIDEBAR_BG"]
    TOPBAR_BG = THEME["TOPBAR_BG"]
    CHAT_OUTER_BG = THEME.get("CHAT_OUTER_BG", THEME.get("CHAT_BG", APP_BG))
    CHAT_INNER_BG = THEME.get("CHAT_INNER_BG", CHAT_OUTER_BG)
    CHAT_BG = CHAT_OUTER_BG
    BORDER = THEME.get("BORDER", "#132242")
    BUBBLE_USER = THEME["BUBBLE_USER"]
    BUBBLE_AI = THEME["BUBBLE_AI"]
    TYPING_BAR_BG = THEME["TYPING_BAR_BG"]
    TYPING_BAR_OUTLINE = THEME["TYPING_BAR_OUTLINE"]
    TYPING_AREA_BG = THEME["TYPING_AREA_BG"]
    MODEL_BG = THEME["MODEL_BG"]
    TEXT_PRIMARY = THEME["TEXT_PRIMARY"]
    TEXT_MUTED = THEME["TEXT_MUTED"]
    TEXT = TEXT_PRIMARY
    SUBTEXT = TEXT_MUTED
    USER_TEXT = TEXT_PRIMARY

def set_theme(new_theme: Dict[str, str]) -> str:
    """Set the global theme and regenerate the QSS. Returns the new QSS string."""
    global THEME, QSS
    merged = dict(THEME_DEFAULT or DEFAULT_THEME)
    if new_theme:
        merged.update({k: str(v) for k, v in new_theme.items()})
    THEME = _apply_theme_aliases(merged)
    _rebind_constants()
    QSS = regenerate_qss(THEME)
    return QSS

def _flatten_theme(d: dict) -> dict:
    """Recursively flatten a nested dict of string values to a single level dict."""
    flat: Dict[str, str] = {}
    if not isinstance(d, dict):
        return flat
    stack = [d]
    while stack:
        cur = stack.pop()
        for k, v in cur.items():
            if isinstance(v, dict):
                stack.append(v)
            else:
                try:
                    flat[str(k)] = str(v)
                except Exception:
                    pass
    return flat

def _nest_theme(flat: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """Nest a flat theme dict into sections defined by SECTION_DEFS."""
    nested: Dict[str, Dict[str, str]] = {}
    # Ensure deterministic order by iterating SECTION_DEFS
    assigned = set()
    for sec, keys in SECTION_DEFS.items():
        grp = {k: flat[k] for k in keys if k in flat}
        if grp:
            nested[sec] = grp
            assigned.update(grp.keys())
    # Place any remaining keys into a Misc section
    # Ignore any keys not in SECTION_DEFS to avoid Misc section
    return nested

def save_theme(theme: Dict[str, str]) -> None:
    """Persist the given theme under 'current' and keep 'default' from THEME_DEFAULT, sectioned."""
    try:
        p = Path(__file__).with_name('theme.json')
        cur = {str(k): str(v) for k, v in (theme or {}).items()}
        dft = dict(THEME_DEFAULT or DEFAULT_THEME)
        data = {
            "default": _nest_theme(dft),
            "current": _nest_theme(cur),
        }
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding='utf-8')
    except Exception:
        pass

def _load_theme() -> tuple:
    """Load nested or flat theme.json. Returns (current, default)."""
    p = Path(__file__).with_name('theme.json')
    if p.exists():
        try:
            raw = p.read_text(encoding='utf-8')
            no_block = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
            no_line = re.sub(r"(^|\s)//.*$", "", no_block, flags=re.M)
            data = json.loads(no_line)
            if isinstance(data, dict) and ("current" in data or "default" in data):
                cur_flat = _flatten_theme(data.get("current", {}))
                dft_flat = _flatten_theme(data.get("default", {}))
                # Merge file default over code defaults
                dft = dict(DEFAULT_THEME); dft.update(dft_flat)
                cur = dict(dft); cur.update(cur_flat)
                return cur, dft
            elif isinstance(data, dict):
                # Legacy flat format -> migrate to nested {default,current}
                cur = dict(DEFAULT_THEME); cur.update({k: str(v) for k, v in data.items()})
                dft = dict(DEFAULT_THEME)
                try:
                    migrated = {"default": _nest_theme(dft), "current": _nest_theme(cur)}
                    p.write_text(json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding='utf-8')
                except Exception:
                    pass
                return cur, dft
        except Exception:
            return dict(DEFAULT_THEME), dict(DEFAULT_THEME)
    return dict(DEFAULT_THEME), dict(DEFAULT_THEME)

THEME, THEME_DEFAULT = _load_theme()

# Normalize theme keys: populate clearer canonical names while preserving old ones
def _apply_theme_aliases(t: Dict[str, str]) -> Dict[str, str]:
    """Populate both old and new theme keys so either naming works."""
    def alias(new_key: str, old_key: str) -> None:
        if new_key not in t and old_key in t:
            t[new_key] = t[old_key]
        if old_key not in t and new_key in t:
            t[old_key] = t[new_key]
    # Backwards compatibility for older keys -> new minimal set
    alias("TEXT_PRIMARY", "TEXT")
    alias("TEXT_MUTED", "SUBTEXT")
    # Outer/inner chat backgrounds
    alias("CHAT_OUTER_BG", "CHAT_BG")
    if "CHAT_BOARD_BG" in t:
        t.setdefault("CHAT_INNER_BG", t["CHAT_BOARD_BG"])
    if "PANEL_BG" in t and "CHAT_INNER_BG" not in t:
        t["CHAT_INNER_BG"] = t["PANEL_BG"]
    if "CHAT_AREA_BG" in t and "CHAT_INNER_BG" not in t:
        t["CHAT_INNER_BG"] = t["CHAT_AREA_BG"]
    t.setdefault("CHAT_INNER_BG", t.get("CHAT_OUTER_BG", t.get("APP_BG", "#212938")))
    # Legacy surfaces to new
    if "CHAT_AREA_BG" in t:
        t.setdefault("CHAT_BG", t["CHAT_AREA_BG"])
    if "PANEL_BG" in t and "CHAT_BG" not in t:
        t["CHAT_BG"] = t["PANEL_BG"]
    # Placeholder maps to muted
    if "PLACEHOLDER" in t:
        t.setdefault("TEXT_MUTED", t["PLACEHOLDER"])
    # Old button aliases
    if "BTN_BG" in t:
        t.setdefault("NEWCHAT_BUTTON_BG", t["BTN_BG"])
    if "DANGER" in t:
        t.setdefault("DELETE_BUTTON_BG", t["DANGER"])
    # Typing bar bg legacy alias
    if "INPUT_BAR_BG" in t:
        t.setdefault("TYPING_BAR_BG", t["INPUT_BAR_BG"])
    if "SURFACE_INPUTBAR_BG" in t:
        t.setdefault("TYPING_BAR_BG", t["SURFACE_INPUTBAR_BG"])
    # Sidebar list
    t.setdefault("CHAT_LIST_BG", t.get("SIDEBAR_BG", t.get("APP_BG", "#2d3748")))
    return t

THEME = _apply_theme_aliases(THEME)

# Base palette (exposed as module constants for convenience)
APP_BG = THEME["APP_BG"]
SIDEBAR_BG = THEME["SIDEBAR_BG"]
TOPBAR_BG = THEME["TOPBAR_BG"]
CHAT_OUTER_BG = THEME.get("CHAT_OUTER_BG", THEME.get("CHAT_BG", APP_BG))
CHAT_INNER_BG = THEME.get("CHAT_INNER_BG", CHAT_OUTER_BG)
CHAT_BG = CHAT_OUTER_BG
BORDER = THEME.get("BORDER", "#132242")
BUBBLE_USER = THEME["BUBBLE_USER"]
BUBBLE_AI = THEME["BUBBLE_AI"]
MODEL_BG = THEME["MODEL_BG"]
ASSETS_DIR = Path(__file__).with_name('assets')
CHEVRON_SVG_PATH = (ASSETS_DIR / 'chevron-down.svg').resolve().as_posix()
CHEVRON_UP_SVG_PATH = (ASSETS_DIR / 'chevron-up.svg').resolve().as_posix()
CHEVRON_DOWN_SMALL_SVG_PATH = (ASSETS_DIR / 'chevron-down-small.svg').resolve().as_posix()
CHEVRON_UP_SMALL_SVG_PATH = (ASSETS_DIR / 'chevron-up-small.svg').resolve().as_posix()

# Fonts
FONT_FAMILY = "Segoe UI, Inter, Arial"
FONT_CHAT = QFont("Segoe UI", 16)
FONT_TS = QFont("Segoe UI", 16)
FONT_SENDER = QFont("Segoe UI", 16, QFont.Bold)

# Canonical (clearer) names exported alongside legacy ones
TEXT_PRIMARY = THEME["TEXT_PRIMARY"]
TEXT_MUTED = THEME["TEXT_MUTED"]
TEXT = TEXT_PRIMARY
SUBTEXT = TEXT_MUTED
USER_TEXT = TEXT_PRIMARY
PANEL_BG = CHAT_OUTER_BG
ACCENT = THEME.get("SEND_BG", THEME["SEND_BG"])  # use primary accent from send color
INPUT_BAR_BG = THEME.get("TYPING_BAR_BG", THEME["TYPING_BAR_BG"])  # legacy export kept for app.py
CHAT_AREA_BG = CHAT_OUTER_BG

# App-wide stylesheet (Qt Style Sheet)
QSS_TEMPLATE = """
* {
    color: %(TEXT_PRIMARY)s;
    font-family: %(FONT_FAMILY)s;
    font-size: 16px;
}
QMainWindow {
    background: %(APP_BG)s;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollArea > QWidget > QWidget#qt_scrollarea_viewport,
QScrollArea > QWidget#qt_scrollarea_viewport {
    background: %(APP_BG)s;
}
/* ChatView viewport transparent so ChatBoard container color shows through */
QScrollArea#ChatView,
QScrollArea#ChatView > QWidget#qt_scrollarea_viewport,
QScrollArea#ChatView > QWidget > QWidget#qt_scrollarea_viewport { background: transparent; }
/* Modern pill-shaped scrollbars for chat view */
QScrollArea#ChatView QScrollBar:vertical { background: transparent; width: 5px; }
QScrollArea#ChatView QScrollBar::handle:vertical { background: rgba(255,255,255,0.25); min-height: 24px; border-radius: 2px; }
QScrollArea#ChatView QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.35); }
QScrollArea#ChatView QScrollBar::sub-line:vertical { height: 0px; width: 0px; margin: 0px; padding: 0px; background: transparent; border: none; }
QScrollArea#ChatView QScrollBar::add-line:vertical { height: 0px; width: 0px; margin: 0px; padding: 0px; background: transparent; border: none; }
QScrollArea#ChatView QScrollBar::add-page:vertical,
QScrollArea#ChatView QScrollBar::sub-page:vertical { background: transparent; }
/* External gutter vertical scrollbar for chat */
QScrollBar#ChatOuterScroll:vertical { background: transparent; width: 5px; margin: 2px 0px 2px 0px; }
QScrollBar#ChatOuterScroll::handle:vertical { background: rgba(255,255,255,0.25); min-height: 24px; border-radius: 2px; }
QScrollBar#ChatOuterScroll::handle:vertical:hover { background: rgba(255,255,255,0.35); }
QScrollBar#ChatOuterScroll::sub-line:vertical { height: 0px; width: 0px; margin: 0px; padding: 0px; background: transparent; border: none; }
QScrollBar#ChatOuterScroll::add-line:vertical { height: 0px; width: 0px; margin: 0px; padding: 0px; background: transparent; border: none; }
QScrollBar#ChatOuterScroll::add-page:vertical,
QScrollBar#ChatOuterScroll::sub-page:vertical { background: transparent; }
/* Optional horizontal bar styling (rare in chat) */
QScrollArea#ChatView QScrollBar:horizontal { background: transparent; height: 10px; margin: 0px 6px 4px 6px; }
QScrollArea#ChatView QScrollBar::handle:horizontal { background: rgba(255,255,255,0.25); min-width: 24px; border-radius: 6px; }
QScrollArea#ChatView QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,0.35); }
QScrollArea#ChatView QScrollBar::add-line:horizontal,
QScrollArea#ChatView QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }
QScrollArea#ChatView QScrollBar::add-page:horizontal,
QScrollArea#ChatView QScrollBar::sub-page:horizontal { background: transparent; }
/* Match input QTextEdit scrollbar to ChatView */
QFrame#EntryWrap QTextEdit QScrollBar:vertical { background: transparent; width: 10px; margin: 10px 0px 10px 0px; }
QFrame#EntryWrap QTextEdit QScrollBar::handle:vertical { background: rgba(255,255,255,0.25); min-height: 24px; border-radius: 6px; }
QFrame#EntryWrap QTextEdit QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.35); }
QFrame#EntryWrap QTextEdit QScrollBar::sub-line:vertical { height: 10px; width: 10px; margin: 0px; padding: 0px; subcontrol-origin: margin; subcontrol-position: top; background: transparent; border: none; image: url(%(CHEVRON_UP_SMALL_SVG_PATH)s); }
QFrame#EntryWrap QTextEdit QScrollBar::add-line:vertical { height: 10px; width: 10px; margin: 0px; padding: 0px; subcontrol-origin: margin; subcontrol-position: bottom; background: transparent; border: none; image: url(%(CHEVRON_DOWN_SMALL_SVG_PATH)s); }
QFrame#EntryWrap QTextEdit QScrollBar::add-page:vertical,
QFrame#EntryWrap QTextEdit QScrollBar::sub-page:vertical { background: transparent; }
QFrame#SideBar {
    background: %(SIDEBAR_BG)s;
    border: none;
    border-radius: 12px;
}
QListWidget, QListWidget::viewport {
    background: %(SIDEBAR_BG)s;
    border: none;
    border-radius: 12px;
    outline: none;
    padding: 2px;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 8px;
}
QListWidget::item:hover {
    background: rgba(125,170,255,0.14);
}
QListWidget::item:selected {
    background: rgba(125,170,255,0.22);
    color: #ffffff;
    border-left: 3px solid %(SEND_BG)s;
    border-radius: 10px;
    margin: 1px 0px;
}
QToolBar {
    background: %(TOPBAR_BG)s;
    border: none;
    spacing: 8px;
    min-height: 64px;
    padding-left: 16px;
    icon-size: 60px; /* ensures toolbar allocates space for larger icons */
}
QToolBar QPushButton, QToolBar QToolButton {
    min-height: 36px;
    padding: 4px 12px;
    font-size: 16px;
    border-radius: 12px;
    font-weight: 600;
}
QComboBox {
    background: %(MODEL_BG)s;
    border: none;
    border-radius: 10px;
    padding: 8px 12px;
    padding-right: 36px; /* space for wider arrow area */
    color: %(TEXT_PRIMARY)s;
    min-height: 36px;
    font-size: 16px;
}
QComboBox:focus { outline: none; border: none; }
QComboBox:hover { background: %(MODEL_HOVER_BG)s; }
QComboBox:pressed { background: %(MODEL_PRESSED_BG)s; }
QComboBox::drop-down { border: none; background: transparent; width: 32px; subcontrol-origin: padding; subcontrol-position: center right; border-top-right-radius: 10px; border-bottom-right-radius: 10px; }
QComboBox::down-arrow { image: url('%(CHEVRON_SVG_PATH)s'); width: 14px; height: 14px; margin-right: 8px; }
/* Pill typing field */
QLineEdit, QTextEdit { background: transparent; border: none; border-radius: 0px; padding: 4px 6px; min-height: 32px; font-size: 16px; color: %(TEXT_PRIMARY)s; }
QLineEdit::placeholder { color: %(TEXT_MUTED)s; }
/* Drop-down customized above; keep popup clean */
/* Popup list view sizing */
QComboBox QAbstractItemView { background: %(MODEL_BG)s; outline: none; border: 1px solid %(BORDER)s; }
QComboBox QAbstractItemView::item { min-height: 22px; padding: 2px 8px; }
QPushButton {
    border: none;
    padding: 6px 14px;
    border-radius: 10px;
    background-color: rgba(255,255,255,0.08);
    color: %(TEXT_PRIMARY)s;
    min-height: 32px;
    font-size: 16px;
    font-weight: 600;
}
QPushButton#DeleteModel { background-color: %(DELETE_BUTTON_BG)s; }
QPushButton#DeleteModel:hover { background-color: %(DELETE_BUTTON_HOVER_BG)s; }
QPushButton#Danger { background-color: %(DELETE_BUTTON_BG)s; }
QPushButton#Danger:hover { background-color: %(DELETE_BUTTON_HOVER_BG)s; }
QPushButton#Secondary { background-color: %(NEWCHAT_BUTTON_BG)s; color:%(TEXT_PRIMARY)s; }
QPushButton#Secondary:hover { background-color: %(NEWCHAT_BUTTON_HOVER_BG)s; }
/* Pill send button lighter than entry */
QPushButton#SendButton { background-color: %(SEND_BG)s; color:%(TEXT_PRIMARY)s; border-radius: 12px; padding: 0px 16px; min-height: 48px; min-width: 96px; font-size: 16px; font-weight: 600; }
QPushButton#SendButton:hover { background-color: %(SEND_HOVER)s; }
QPushButton#SendButton[active="true"] { background-color: %(SEND_ACTIVE)s; color:%(TEXT_PRIMARY)s; }
/* Icon-only QToolButton variant used in input bar */
QToolButton#SendButton { background-color: %(SEND_BG)s; color:#FFFFFF; border: 0px; border-radius: 10px; }
QToolButton#SendButton:hover { background-color: %(SEND_HOVER)s; }
QToolButton#SendButton[active="true"] { background-color: %(SEND_ACTIVE)s; }
QToolButton#SendButton[active="true"]:hover { background-color: %(SEND_ACTIVE)s; }
/* Bottom input row card */
QFrame#InputBar { background-color: %(TYPING_BAR_BG)s; border: 1px solid %(TYPING_BAR_OUTLINE)s; border-radius: 16px; }
/* Outer pill: merged typing area background */
QFrame#EntryWrap { background-color: %(TYPING_AREA_BG)s; border-radius: 999px; padding: 6px 10px; }
QFrame#EntryWrap QLineEdit, QFrame#EntryWrap QTextEdit { background: transparent; border: none; }
/* Icon-only refresh tool button */
QToolButton#RefreshTool { background: transparent; padding: 0px; border-radius: 8px; color: %(TEXT_PRIMARY)s; min-width: 36px; min-height: 36px; max-width: 36px; max-height: 36px; padding: 8px; qproperty-iconSize: 36px 36px; }
QToolButton#RefreshTool:hover { background: rgba(255,255,255,0.08); }
/* Settings tool button (separate so you can size it independently) */
QToolButton#SettingsTool { background: transparent; padding: 0px; border-radius: 8px; color: %(TEXT_PRIMARY)s; min-width: 36px; min-height: 36px; max-width: 36px; max-height: 36px; padding: 8px; qproperty-iconSize: 36px 36px; }
QToolButton#SettingsTool:hover { background: rgba(255,255,255,0.08); }
/* Top bar 'MODEL SELECTOR' label */
QLabel#ModelSelectorLabel { color: %(TEXT_PRIMARY)s; font-weight: 800; font-size: 20px; padding: 0px 2px; text-align: right; }
/* Top bar 'CONTEXT USAGE' label */
QLabel#ContextLabel { color: %(TEXT_PRIMARY)s; font-weight: 800; font-size: 20px; padding: 0px 2px; text-align: right; }
/* Settings dialog button states */
QPushButton#TSave[changed="true"] { background-color: %(SEND_BG)s; }
QPushButton#TRestore[needsReset="true"] { background-color: %(DELETE_BUTTON_BG)s; }
/* Settings dialog button hovers */
QPushButton#TSave:hover { background-color: rgba(255,255,255,0.12); }
QPushButton#TSave[changed="true"]:hover { background-color: %(SEND_HOVER)s; }
QPushButton#TRestore:hover { background-color: rgba(255,255,255,0.12); }
QPushButton#TRestore[needsReset="true"]:hover { background-color: %(DELETE_BUTTON_HOVER_BG)s; }
QPushButton#TClose:hover { background-color: rgba(255,255,255,0.12); }
/* Settings dialog tabs - larger font, seamless blend */
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: transparent; border: none; padding: 8px 16px; margin: 0px 8px; font-size: 18px; font-weight: 600; color: %(TEXT_PRIMARY)s; }
QTabBar::tab:selected { color: %(TEXT_PRIMARY)s; background: transparent; }
QTabBar::tab:!selected { color: %(TEXT_MUTED)s; background: transparent; }
QTabBar::tab:focus { outline: none; }
/* Settings dialog scrollbar - thin handle only */
QScrollArea#SettingsScroll QScrollBar:vertical { background: transparent; width: 5px; margin: 2px 0px 2px 0px; }
QScrollArea#SettingsScroll QScrollBar::handle:vertical { background: rgba(255,255,255,0.25); min-height: 24px; border-radius: 2px; }
QScrollArea#SettingsScroll QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.35); }
QScrollArea#SettingsScroll QScrollBar::sub-line:vertical, QScrollArea#SettingsScroll QScrollBar::add-line:vertical { height: 0px; width: 0px; margin: 0px; padding: 0px; background: transparent; border: none; }
QScrollArea#SettingsScroll QScrollBar::add-page:vertical, QScrollArea#SettingsScroll QScrollBar::sub-page:vertical { background: transparent; }
/* Settings dialog sections */
QFrame#SettingsSection { background: transparent; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }
QFrame#SettingsSection QLabel#SectionHeader { color: %(TEXT_PRIMARY)s; margin-bottom: 2px; }
/* Kebab (⋮) per-chat menu button */
QToolButton#Kebab { background: transparent; padding: 0px 2px; border-radius: 6px; color: %(TEXT_PRIMARY)s; font-size: 24px; min-width: 0px; }
QToolButton#Kebab:hover { background: rgba(255,255,255,0.08); }
QLabel#Msg, QLabel#Ts, QLabel#Sender { background: transparent; }
/* Centered date separator */
QLabel#DateSep { color: %(TEXT_MUTED)s; background: transparent; font-size: 14px; font-weight: 600; padding: 6px 8px; margin: 6px 0px; }
/* Chat bubbles */
QFrame#Bubble { background: transparent; border: none; border-radius: 12px; }
QFrame#Bubble[sender="user"] { background: %(BUBBLE_USER)s; }
QFrame#Bubble[sender="ai"] { background: %(BUBBLE_AI)s; }
QFrame#Bubble QLabel#Msg { background: transparent; }
QFrame#Bubble QLabel#Ts { color: %(TEXT_MUTED)s; background: transparent; }
QFrame#Bubble QLabel#Tok { color: %(TEXT_MUTED)s; background: transparent; font-style: italic; }
QFrame#Bubble[sender="user"] QLabel#Msg { color: %(USER_TEXT)s; }
QFrame#Bubble[sender="ai"] QLabel#Msg { color: %(TEXT_PRIMARY)s; }
/* Inline context usage row under input */
QWidget#ContextRow { background: transparent; }
QLabel#ContextInlineLabel { color: %(TEXT_MUTED)s; background: transparent; font-size: 12px; font-weight: 600; }
/* Sidebar title */
QLabel#SideTitle { color: %(TEXT_PRIMARY)s; font-size: 16px; font-weight: 700; padding: 0px 2px 6px 2px; }
/* Chat board container */
QFrame#ChatBoard { background-color: %(CHAT_INNER_BG)s; border: none; border-radius: 12px; }
/* Main panel container */
QFrame#MainPanel { background: %(CHAT_OUTER_BG)s; border: none; border-radius: 12px; }
/* Icon-only send button (PNG) with round background using Secondary colors */
QFrame#InputBar QPushButton#SendIcon,
QFrame#InputBar QToolButton#SendIcon,
QPushButton#SendIcon,
QToolButton#SendIcon {
    background: %(SEND_ICON_BG)s;
    background-color: %(SEND_ICON_BG)s;
    border: none;
    outline: none;
    padding: 0px;
    margin: 0px;
    min-width: 48px;
    min-height: 48px;
    max-width: 48px;
    max-height: 48px;
    border-radius: 999px;
}
QFrame#InputBar QPushButton#SendIcon:hover,
QFrame#InputBar QToolButton#SendIcon:hover,
QPushButton#SendIcon:hover,
QToolButton#SendIcon:hover { background: %(SEND_ICON_HOVER_BG)s; background-color: %(SEND_ICON_HOVER_BG)s; }
QFrame#InputBar QPushButton#SendIcon:pressed,
QFrame#InputBar QToolButton#SendIcon:pressed,
QPushButton#SendIcon:pressed,
QToolButton#SendIcon:pressed { background: %(SEND_ICON_HOVER_BG)s; background-color: %(SEND_ICON_HOVER_BG)s; }

/* Chat history list */
QListWidget#ChatList { background: %(CHAT_LIST_BG)s; border: none; color: %(TEXT_PRIMARY)s; }
QListWidget#ChatList::item { background: %(CHAT_LIST_BG)s; padding: 8px; margin: 4px 6px; border-radius: 8px; }
QListWidget#ChatList::item:hover { background: %(CHAT_LIST_ITEM_HOVER_BG)s; }
QListWidget#ChatList::item:selected { background: %(CHAT_LIST_ITEM_SELECTED_BG)s; color: %(TEXT_PRIMARY)s; }
/* Remove down-arrow indicators on menu buttons */
QToolButton::menu-indicator { image: none; width: 0px; height: 0px; }
"""
QSS = regenerate_qss(THEME)
