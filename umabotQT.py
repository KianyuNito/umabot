"""UmaBot - PySide6 GUI (port of umabot.py). Run with `uv run python umabotQT.py`."""
import ctypes
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import cv2
import keyboard
from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QRectF, QSize, Qt, QProcess, QThread, Signal
from PySide6.QtGui import QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

# Create QApplication before engine: config.py sets DPI awareness on import, and Qt must set its own first.
# The capture child process runs without Qt, so it skips this and keeps the config.py setting.
if "--capture" not in sys.argv:
    app = QApplication.instance() or QApplication(sys.argv)

import engine  # noqa: E402
import vision  # noqa: E402
from config import BASE, CARATS_CSV, RECORD_DIR, STOP_KEY, PAUSE_KEY, SKIP_KEY, START_KEY  # noqa: E402
from carats_history import ACTION_LABELS, read_carats  # noqa: E402
from app_store import catalog, store  # noqa: E402
from skill_store import SkillStore  # noqa: E402

PALETTE = {
    "rail_bg": "#735CE6",
    "rail_active": "#8976EB",
    "rail_fg": "#FFFFFF",
    "rail_muted": "#D8D2FA",
    "sidebar_bg": "#242330",
    "canvas_bg": "#1C1B26",
    "card_bg": "#2B2A3B",
    "card_alt": "#242332",
    "border": "#36354A",
    "text": "#F4F4F8",
    "muted": "#A6A4BC",
    "accent": "#735CE6",
    "accent_hover": "#846FF0",
    "hover": "#38374E",
    "disabled_bg": "#343347",
    "disabled_fg": "#666985",
    "log_bg": "#16151E",
    "warn": "#F39C12",
}

RAIL_WIDTH = 56
DEFAULT_KEYS = {"start": START_KEY, "stop": STOP_KEY, "pause": PAUSE_KEY, "skip": SKIP_KEY}
RAIL_EXPANDED_WIDTH = 180   # the ☰ button opens the rail to show labels
TASKS_MIN, TASKS_MAX = 300, 480
TASKS_MIN_WINDOW = 1100   # window width below which the Tasks column is hidden
MASCOT_HEIGHT = 220       # the mascot is scaled to this height; change it to taste
CONTROL_WIDTH = 240       # every dropdown and text box in an action card is this wide
BAR_GUTTER = 24           # the scroll bar column; the cards, toolbar and log all stop this far short of the edge
PAD = 24                  # the gap between the rail, the two columns and the window edge
STATUS_TEXT = {"done": "Done", "failed": "Failed", "skipped": "Skipped", "pending": "Pending"}
STATUS_COLOUR = {"done": "#4ADE80", "failed": "#FF7B6B", "skipped": "#A6A4BC", "pending": "#A6A4BC"}
TASK_GOOD = "#2ECC71"
TASK_BAD = "#E74C3C"

STYLE = f"""
QWidget {{ font-family: Nunito; font-size: 10pt; color: {PALETTE['text']}; }}
QWidget#main {{ background: {PALETTE['canvas_bg']}; }}
QFrame#rail {{ background: {PALETTE['rail_bg']}; }}
QFrame#sidebar {{ background: {PALETTE['sidebar_bg']}; }}
QFrame#tasks {{ background: {PALETTE['sidebar_bg']}; }}
QFrame#card {{ background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['border']}; border-radius: 8px; }}
QLabel#caption {{ color: {PALETTE['muted']}; font-size: 9pt; font-weight: bold; }}
QLabel#title {{ font-size: 15pt; font-weight: bold; }}
QLabel#status {{ font-size: 18pt; font-weight: bold; }}
QLabel#warn {{ color: {PALETTE['warn']}; }}
QPushButton {{ min-height: 32px; padding: 0 12px; border: 0; border-radius: 6px;
              background: {PALETTE['card_alt']}; color: {PALETTE['text']}; }}
QPushButton:hover {{ background: {PALETTE['hover']}; }}
QPushButton:disabled {{ background: {PALETTE['disabled_bg']}; color: {PALETTE['disabled_fg']}; }}
QPushButton#primary {{ background: {PALETTE['accent']}; color: #FFFFFF; }}
QPushButton#primary:hover {{ background: {PALETTE['accent_hover']}; }}
QPushButton#rail, QPushButton#railactive {{ background: transparent; border: 0; border-radius: 0;
    min-height: 48px; padding: 0; }}
QPushButton#rail QLabel {{ color: {PALETTE['rail_muted']}; font-size: 12pt; font-weight: bold; }}
QPushButton#railactive QLabel {{ color: {PALETTE['rail_fg']}; font-size: 12pt; font-weight: bold; }}
QPushButton#rail:hover, QPushButton#railactive:hover {{ background: {PALETTE['rail_active']}; }}
QLineEdit {{ min-height: 32px; padding: 0 8px; border: 1px solid {PALETTE['border']};
            border-radius: 6px; background: {PALETTE['card_alt']}; }}
QPlainTextEdit#log {{ background: {PALETTE['log_bg']}; font-family: Consolas; border: 0; border-radius: 6px; }}
QProgressBar {{ background: {PALETTE['card_alt']}; border: 0; border-radius: 8px; min-height: 22px; text-align: center; }}
QProgressBar::chunk {{ background: {PALETTE['accent']}; border-radius: 8px; }}
QCheckBox {{ spacing: 8px; }}
QToolTip {{ background: {PALETTE['card_bg']}; color: {PALETTE['text']}; border: 1px solid {PALETTE['border']}; padding: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: {BAR_GUTTER}px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {PALETTE['disabled_fg']}; min-height: 32px; margin: 0 {(BAR_GUTTER - 6) // 2}px; border-radius: 3px; }}
QScrollBar::handle:vertical:hover {{ background: {PALETTE['muted']}; }}
QScrollArea#taskslist QScrollBar:vertical {{ margin: 28px 0 0 0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QComboBox {{ min-height: 32px; padding: 0 8px; border: 1px solid {PALETTE['border']};
            border-radius: 6px; background: {PALETTE['card_alt']}; }}
QComboBox::drop-down {{ border: 0; width: 28px; }}
QScrollArea#actions, QScrollArea#sidelist {{ background: transparent; border: 0; }}
QWidget#actions_viewport, QWidget#actions_inner, QWidget#sidelist_viewport, QWidget#sidelist_inner {{ background: transparent; }}
QFrame#resolved {{ background: {PALETTE['canvas_bg']}; border: 1px solid {PALETTE['border']}; border-radius: 8px; }}
QLabel#cardtitle {{ font-weight: bold; }}
QLabel#muted {{ color: {PALETTE['muted']}; font-size: 9pt; }}
QFrame#taskrow {{ border-bottom: 1px solid {PALETTE['border']}; }}
QScrollArea#taskslist {{ background: transparent; border: 0; }}
QWidget#tasks_viewport, QWidget#tasks_inner {{ background: transparent; }}
QWidget#actions_viewport, QWidget#actions_inner {{ background: transparent; }}
"""


def fonts_dir():
    if (BASE / "fonts").exists() or not hasattr(sys, "_MEIPASS"):   # next to the exe first, like the Tk version
        return BASE / "fonts"
    return Path(sys._MEIPASS) / "fonts"


def assets_dir():
    if (BASE / "assets").exists() or not hasattr(sys, "_MEIPASS"):   # next to the exe first, like the Tk version
        return BASE / "assets"
    return Path(sys._MEIPASS) / "assets"


def load_fonts():
    """Register the .ttf files in the fonts folder for this program only (no install needed)."""
    for p in fonts_dir().glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(p))


def dark_title_bar(window):
    """Windows only: dark title bar, matching the dark palette."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
    except Exception:
        pass


RAIL_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
RAIL_ICONS = {
    "Menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "Main": '<path d="M3 11 12 3l9 8v10h-6v-6H9v6H3z"/>',
    "Check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "Play": '<path d="M7 5v14l12-7z"/>',
    "Settings": ('<path d="M3 6h3.5M11.5 6H21M3 12h11.5M19.5 12H21M3 18h7.5M15.5 18H21"/>'
                 '<circle cx="9" cy="6" r="2.5"/><circle cx="17" cy="12" r="2.5"/><circle cx="13" cy="18" r="2.5"/>'),
}


def rail_icon(name, colour, size=24):
    """One rail icon in the given colour. Drawn at twice the size so it stays sharp on high-DPI screens."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    svg = RAIL_SVG.format(c=colour, body=RAIL_ICONS[name]).encode()
    QSvgRenderer(QByteArray(svg)).render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


class FlowLayout(QLayout):
    """Puts widgets in a row and moves the ones that don't fit onto the next line. Qt has no built-in version."""
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items, self._spacing = [], spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect, test_only):
        m = self.contentsMargins()
        left, right = rect.x() + m.left(), rect.right() - m.right()
        x, y, line_h = left, rect.y() + m.top(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x > left and x + hint.width() > right:     # start a new line; the first item on a line always fits
                x, y = left, y + line_h + self._spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h + m.bottom() - rect.y()


class HandButton(QPushButton):
    """Button with the hand pointer when enabled and the arrow when disabled (desktop UI rules)."""
    def __init__(self, text, objectName=""):
        super().__init__(text, objectName=objectName)
        self._set_pointer()

    def _set_pointer(self):
        self.setCursor(Qt.PointingHandCursor if self.isEnabled() else Qt.ArrowCursor)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            self._set_pointer()


class RefreshingCombo(QComboBox):
    """Dropdown that can rebuild its items each time it opens (Qt has no postcommand). The wheel scrolls the
    list around it instead of changing the value, as in the Tk version."""
    def __init__(self, refresh=None):
        super().__init__()
        self.refresh = refresh
        self.setCursor(Qt.PointingHandCursor)

    def showPopup(self):
        if self.refresh:
            self.refresh(self)
        super().showPopup()

    def wheelEvent(self, event):
        event.ignore()


class Worker(QThread):
    """Runs engine.run_all off the GUI thread. The engine never touches widgets; it only emits these signals."""
    log = Signal(str)
    progress = Signal(int, int)
    step = Signal(str, int, int, str)

    def __init__(self, title, stop_event, skip_event, pause_event, only=None, start_at=None):
        super().__init__()
        self.title, self.stop_event, self.skip_event = title, stop_event, skip_event
        self.pause_event = pause_event
        self.only, self.start_at = only, start_at

    def run(self):
        try:
            engine.run_all(self.title, self.log.emit, self.stop_event, only=self.only,
                           start_at=self.start_at, skip_event=self.skip_event,
                           progress=self.progress.emit,
                           step=self.step.emit, pause_event=self.pause_event)
        except Exception:  # noqa
            self.log.emit("ERROR: " + traceback.format_exc())


class MainWindow(QMainWindow):
    hotkey_pressed = Signal(str)  # action name; the keyboard hook runs on another thread, so it emits this instead of calling the UI
    key_captured = Signal(str, str)  # (action, key) from the key-binding thread
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UmaBot")
        self.resize(1160, 860)

        root = QWidget(objectName="main")
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.rail = QFrame(objectName="rail")
        self.rail.setFixedWidth(RAIL_WIDTH)
        self.main_area = QFrame(objectName="main_area")
        self.tasks_col = QFrame(objectName="tasks")
        self.tasks_col.setMinimumWidth(TASKS_MIN)
        self.tasks_col.setMaximumWidth(TASKS_MAX)

        self.main_screen = QWidget()
        mrow = QHBoxLayout(self.main_screen)
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.setSpacing(0)
        mrow.addWidget(self.tasks_col, 2)
        mrow.addWidget(self.main_area, 5)
        engine.init_db()                  # first: the Settings page reads the saved shop options
        self.pages = QStackedWidget()
        self.pages.addWidget(self.main_screen)
        self.pages.addWidget(self._build_settings())
        self.pages.addWidget(self._build_skills())
        self.pages.addWidget(self._build_history())
        row.addWidget(self.rail)
        row.addWidget(self.pages, 1)
        self.worker = None
        self.capture_proc = None  # the Tk capture dialog, running in its own process
        self.vars = {}           # action name -> {"enabled": QCheckBox, "settings": {key: widget}}
        self.status_vars = {}    # action name -> status QLabel
        self.start_vars = {}     # action name -> "Start at" dropdown
        self.stop_event = threading.Event()
        self.skip_event = threading.Event()
        self.pause_event = threading.Event()
        self.task_state = {}      # name -> (done, total, status), drawn in step 6
        self.hotkey_pressed.connect(self._on_hotkey)
        self.key_captured.connect(self._on_key_captured)
        self.capturing = None     # action currently waiting for a key, or None
        self.hotkey_handles = {}  # action -> keyboard handle
        self._register_hotkeys()
        self._build_tasks()       # first: _build_main() calls refresh_missing(), which uses missing_lbl
        self._build_main()
        self._build_rail()
        self._fit_tasks()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_tasks()

    def closeEvent(self, event):
        self.stop_event.set()
        if self.worker and self.worker.isRunning():
            # shortcut: waits 5 s; the engine checks for stop inside its waits, so most steps end in well under that.
            # upgrade to a forced stop if a run is still going after the close.
            self.worker.wait(5000)
        for handle in self.hotkey_handles.values():
            keyboard.remove_hotkey(handle)
        super().closeEvent(event)

    def _fit_tasks(self):
        self.tasks_col.setVisible(self.width() >= TASKS_MIN_WINDOW)

    # ---------------- key bindings ----------------
    def _key(self, action):
        return store.app_setting(f"key_{action}", DEFAULT_KEYS[action])

    def _register_hotkeys(self):
        for handle in self.hotkey_handles.values():
            keyboard.remove_hotkey(handle)
        self.hotkey_handles = {a: keyboard.add_hotkey(self._key(a), self.hotkey_pressed.emit, args=(a,))
                               for a in DEFAULT_KEYS}

    def _on_hotkey(self, action):
        if self.capturing:                      # ignore hotkeys while a key is being bound
            return
        if action == "stop":
            self._hotkey_stop()
        elif action == "start":
            self.start()                        # start() already does nothing while a run is going
        elif self.worker and self.worker.isRunning():
            if action == "pause":
                self.toggle_pause()
            elif action == "skip":
                self.skip_action()

    def _build_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("Settings", objectName="title"))
        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.addWidget(self._caption("KEY BINDINGS"))
        self.key_buttons = {}
        for action, label in (("start", "Start"), ("stop", "Stop"), ("pause", "Pause"), ("skip", "Skip step")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label), 1)
            btn = self._button("", lambda a=action: self._capture_key(a))
            btn.setMinimumWidth(140)
            row.addWidget(btn)
            self.key_buttons[action] = btn
            cl.addLayout(row)
        layout.addWidget(card)
        shop = store.action("daily_shop")
        shop_card = QFrame(objectName="card")
        sl = QVBoxLayout(shop_card)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.addWidget(self._caption("DAILY SHOP: WHAT TO BUY"))
        for key in shop["info"].get("settings_page", []):
            box = QCheckBox(key[len("buy_"):].replace("_", " ").capitalize())
            box.setCursor(Qt.PointingHandCursor)
            box.setChecked(bool(shop["settings"].get(key)))
            box.toggled.connect(lambda on, k=key: self._save_shop_option(k, on))
            sl.addWidget(box)
        layout.addWidget(shop_card)
        layout.addStretch(1)
        self._refresh_key_buttons()
        return page

    def _build_skills(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("Skills", objectName="title"))
        layout.addWidget(QLabel("Must buy skills get the points first, top of the list first. "
                                "One that is not found, or does not fit in the points left, is skipped."))
        cols = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        self.skill_search = QLineEdit()
        self.skill_search.setPlaceholderText("Search skills")
        self.skill_search.textChanged.connect(self._filter_skills)
        self.skill_list = QListWidget()
        left.addWidget(self.skill_search)
        left.addWidget(self.skill_list)
        left.addWidget(self._button("Add to must buy", self._add_must_buy))
        self.must_list = QListWidget()
        self.must_list.setDragDropMode(QAbstractItemView.InternalMove)    # drag to reorder
        for name in store.app_setting("must_buy", "").splitlines():
            if name:
                self._add_must_item(name)
        self._renumber_must()
        model = self.must_list.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.rowsMoved):
            signal.connect(lambda *_: self._must_changed())               # add, remove and reorder
        right.addWidget(self._caption("MUST BUY (top = first)"))
        right.addWidget(self.must_list)
        right.addWidget(self._button("Remove", self._remove_must_buy))
        cols.addLayout(left)
        cols.addLayout(right)
        layout.addLayout(cols, 1)
        return page

    def _fill_skills(self):
        self.skill_list.clear()
        self.skill_list.addItems(sorted(SkillStore(str(BASE / "skills.db")).names()))
        self._filter_skills(self.skill_search.text())

    def _filter_skills(self, text):
        for i in range(self.skill_list.count()):
            item = self.skill_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def _add_must_item(self, name):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, name)         # the plain name; the text shown carries the rank number
        self.must_list.addItem(item)

    def _add_must_buy(self):
        have = self._must_names()
        for item in self.skill_list.selectedItems():
            if item.text() not in have:
                self._add_must_item(item.text())

    def _remove_must_buy(self):
        for item in self.must_list.selectedItems():
            self.must_list.takeItem(self.must_list.row(item))

    def _must_names(self):
        return [self.must_list.item(i).data(Qt.UserRole) for i in range(self.must_list.count())]

    def _renumber_must(self):
        for i in range(self.must_list.count()):
            item = self.must_list.item(i)
            item.setText(f"{i + 1}. {item.data(Qt.UserRole)}")

    def _must_changed(self):
        self._renumber_must()
        store.set_app_setting("must_buy", "\n".join(n for n in self._must_names() if n))

    def _build_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("History", objectName="title"))
        self.history_filter = QComboBox()
        self.history_filter.addItems(["All", "Team trials", "Independent"])
        self.history_filter.currentIndexChanged.connect(lambda _i: self._fill_history())
        self.history_list = QListWidget()
        self.history_list.setIconSize(QSize(100, 36))
        layout.addWidget(self.history_filter)
        layout.addWidget(self.history_list, 1)
        return page

    def _fill_history(self):
        want = {1: "team_trials", 2: "independent_run"}.get(self.history_filter.currentIndex())
        self.history_list.clear()
        for r in read_carats(CARATS_CSV):
            if want and r["action"] != want:
                continue
            w = r["when"]
            clock = f"{(w.hour % 12) or 12}:{w:%M} {'am' if w.hour < 12 else 'pm'}"
            item = QListWidgetItem(f"{ACTION_LABELS.get(r['action'], 'Unknown action')} · "
                                   f"{w:%b} {w.day}, {clock} · {r['carats']} carats")
            pix = QPixmap(str(RECORD_DIR / r["image"])) if r["image"] else QPixmap()
            if not pix.isNull():
                item.setIcon(QIcon(pix))
            self.history_list.addItem(item)

    def _save_shop_option(self, key, on):
        action = store.action("daily_shop")
        store.save("daily_shop", action["enabled"], dict(action["settings"], **{key: on}))
        self.refresh_missing()             # the pictures a run needs depend on what is ticked

    def _refresh_key_buttons(self):
        for action, btn in self.key_buttons.items():
            btn.setText(self._key(action).upper())

    def _capture_key(self, action):
        if self.capturing:                      # one capture at a time
            return
        self.capturing = action
        self.key_buttons[action].setText("Press a key...")
        threading.Thread(target=lambda: self.key_captured.emit(action, keyboard.read_hotkey(suppress=False)),
                         daemon=True).start()

    def _on_key_captured(self, action, key):
        self.capturing = None
        taken = any(self._key(a) == key for a in DEFAULT_KEYS if a != action)
        if key == "esc":                        # Esc cancels, so it can't be bound
            pass
        elif taken:
            QMessageBox.information(self, "Key in use", f"{key.upper()} is already used by another action.")
        else:
            store.set_app_setting(f"key_{action}", key)
            self._register_hotkeys()
        self._refresh_key_buttons()

    def _show_screen(self, index):
        self.pages.setCurrentIndex(index)
        if index == 2:
            self._fill_skills()                 # a scan may have changed the list since the page was built
        elif index == 3:
            self._fill_history()
        for i, btn in enumerate(self.screen_buttons):
            btn.setObjectName("railactive" if i == index else "rail")
            for w in (btn, *btn.findChildren(QLabel)):      # the labels take their colour from the button's name
                w.style().unpolish(w)
                w.style().polish(w)
        self._paint_icons(index)

    # ---------------- helpers ----------------
    def _button(self, text, handler=None, primary=False):
        b = HandButton(text, objectName="primary" if primary else "")
        if handler:
            b.clicked.connect(lambda _checked=False: handler())
        return b

    def _caption(self, text):
        return QLabel(text, objectName="caption")

    def _inset(self, widget):
        """Wrap a widget so it stops BAR_GUTTER short of the right edge, where the cards in a scroll list end."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, BAR_GUTTER, 0)
        row.addWidget(widget)
        return box

    # ---------------- tasks column: today's run card ----------------
    def _build_tasks(self):
        layout = QVBoxLayout(self.tasks_col)
        layout.setContentsMargins(PAD, 16, 0, 16)
        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.addWidget(self._caption("TODAY'S RUN"))
        top = QHBoxLayout()
        self.status_lbl = QLabel("Ready", objectName="status")
        self.status_lbl.setWordWrap(True)
        top.addWidget(self.status_lbl)
        top.addStretch(1)
        self.missing_lbl = QLabel(objectName="warn")
        self.missing_lbl.setWordWrap(True)
        top.addWidget(self.missing_lbl)
        cl.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        cl.addWidget(self.bar)
        layout.addWidget(self._inset(card))
        scroll = QScrollArea(objectName="taskslist")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("tasks_viewport")
        inner = QWidget(objectName="tasks_inner")
        self.tasks_layout = QVBoxLayout(inner)
        self.tasks_layout.setContentsMargins(0, 0, 0, 0)
        self.tasks_layout.setSpacing(8)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        mascot = assets_dir() / "mascot.png"
        if mascot.exists():
            pic = QLabel()
            pic.setPixmap(QPixmap(str(mascot)).scaledToHeight(MASCOT_HEIGHT, Qt.SmoothTransformation))
            pic.setAlignment(Qt.AlignCenter)
            layout.addWidget(self._inset(pic))
        self._refresh_tasks()

    # ---------------- main column: header, banner, log ----------------
    def _build_main(self):
        layout = QVBoxLayout(self.main_area)
        layout.setContentsMargins(PAD, 16, PAD - BAR_GUTTER, 16)
        layout.setSpacing(8)

        layout.addWidget(QLabel("UmaBot - Umamusume Daily Automation", objectName="title"))

        conn = QHBoxLayout()
        conn.addWidget(QLabel("Game window title contains:"))
        self.title_edit = QLineEdit(store.app_setting("window_title", engine.DEFAULT_WINDOW_TITLE))
        self.title_edit.setFixedWidth(220)
        self.title_edit.textChanged.connect(lambda t: store.set_app_setting("window_title", t))
        conn.addWidget(self.title_edit)
        conn.addWidget(self._button("Test connection", self.test_connection))
        conn.addWidget(self._button("Detect screen", self.detect_screen))
        conn.addStretch(1)
        layout.addLayout(conn)

        banner = QFrame(objectName="card")
        bl = FlowLayout(banner, spacing=8)
        bl.setContentsMargins(12, 8, 12, 8)
        self.start_btn = self._button("Start", self.start, primary=True)
        self.stop_btn = self._button("Stop", self.stop)
        self.stop_btn.setEnabled(False)
        self.skip_btn = self._button("Skip step", self.skip_action)
        self.skip_btn.setEnabled(False)
        self.pause_btn = self._button("Pause", self.toggle_pause)
        self.pause_btn.setEnabled(False)
        self.capture_btn = self._button("Capture template", self.capture_template)
        self.toggle_log_btn = self._button("Hide log", self.toggle_log)
        self.toggle_log_btn.setMinimumWidth(96)            # keeps its width when the label changes
        for b in (self.start_btn, self.stop_btn, self.skip_btn, self.pause_btn, self.capture_btn,
                  self._button("Reset today", self.reset_today),
                  self._button("Open folder", lambda: os.startfile(engine.BASE)),
                  self._button("Copy log", self.copy_log),
                  self._button("Clear log", self.clear_log),
                  self.toggle_log_btn):
            bl.addWidget(b)
        layout.addWidget(self._inset(banner))

        layout.addWidget(self._caption("ACTIONS"))
        layout.addWidget(self._build_actions_panel(), 3)

        self.log_card = QFrame(objectName="card")
        ll = QVBoxLayout(self.log_card)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.addWidget(self._caption("ACTIVITY LOG"))
        self.log_box = QPlainTextEdit(objectName="log")
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(5000)
        self.log_box.setMinimumHeight(120)
        ll.addWidget(self.log_box)
        self.log_row = self._inset(self.log_card)
        layout.addWidget(self.log_row, 1)
        self.log_visible = True

        self.refresh_missing(announce=True)

    # ---------------- logging ----------------
    def log(self, text):
        self.log_box.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {text}")

    def copy_log(self):
        QApplication.clipboard().setText(self.log_box.toPlainText())
        self.log("Log copied to clipboard")

    def clear_log(self):
        self.log_box.clear()
        self.log("Log cleared")

    def toggle_log(self):
        self.log_visible = not self.log_visible
        self.log_row.setVisible(self.log_visible)
        self.toggle_log_btn.setText("Hide log" if self.log_visible else "Show log")

    def refresh_missing(self, announce=False):
        if announce:
            have = [n[len("screen_"):] for n in catalog.markers() if catalog.exists(n)]
            self.log("Screen markers captured: " + (", ".join(have) if have else "none yet (optional)"))
        missing = engine.missing_templates()
        total = len(engine.required_templates())
        if missing:
            self.missing_lbl.setText(f"Templates still needed: {len(missing)} of {total} (use 'Capture template')")
            if announce:
                self.log("Missing templates: " + ", ".join(missing))
        else:
            self.missing_lbl.setText("")       # label stays in place, so nothing shifts

    # ---------------- connection and checklist ----------------
    def test_connection(self):
        try:
            game = engine.GameWindow(self.title_edit.text())
            l, t, w, h = game.client_rect()
            img = game.screenshot()
            engine.DEBUG_DIR.mkdir(exist_ok=True)
            cv2.imwrite(str(engine.DEBUG_DIR / "test_capture.png"), img)
            self.log(f"Found game window: {w}x{h} px at ({l},{t}). Test capture saved to debug\\test_capture.png")
            QMessageBox.information(self, "Connected",
                                    f"Found the game window ({w}x{h}).\nCheck debug\\test_capture.png to see what the bot sees.")
        except Exception as e:  # noqa
            self.log(f"Test failed: {e}")
            QMessageBox.critical(self, "Not connected", str(e))

    def detect_screen(self):
        try:
            game = engine.GameWindow(self.title_edit.text())
            game.focus()
            time.sleep(0.6)
            name, score, scores = vision.detect_screen(game.screenshot())
        except Exception as e:  # noqa
            QMessageBox.critical(self, "Can't detect", str(e))
            return
        if not scores:
            msg = ("No screen markers captured yet. Use 'Capture template' and name them "
                   + ", ".join(catalog.markers()) + ".")
        else:
            table = ", ".join(f"{k} {v:.2f}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1]))
            msg = (f"Detected screen: {name} (score {score:.2f})" if name
                   else "Unrecognised screen (nothing reached the match threshold)") + f"\nScores: {table}"
        self.log(msg.replace("\n", " | "))
        QMessageBox.information(self, "Detect screen", msg)

    def reset_today(self):
        answer = QMessageBox.question(self, "Reset", "Clear today's checklist marks?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        store.reset_today()
        self.task_state = {}
        self.refresh_status()
        self._refresh_tasks()
        self.log("Today's checklist reset.")

    # ---------------- rail ----------------
    def _build_rail(self):
        layout = QVBoxLayout(self.rail)
        layout.setContentsMargins(0, 40, 0, 0)
        layout.setSpacing(8)
        self.menu_open = False
        self.rail_items = []                  # (button, label widget, icon widget, icon name)
        for icon, label in (("Menu", "Menu"), ("Main", "Main"), ("Check", "History"),
                            ("Play", "Skills"), ("Settings", "Settings")):
            btn = QPushButton(objectName="rail")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(48)
            inner = QHBoxLayout(btn)
            inner.setContentsMargins(16, 0, 16, 0)
            inner.setSpacing(16)              # the gap between icon and text, the same on every tab
            icon_lbl, text_lbl = QLabel(), QLabel(label)
            icon_lbl.setFixedSize(24, 24)     # a fixed slot, so the text starts at the same place on every tab
            icon_lbl.setAlignment(Qt.AlignCenter)
            for lbl in (icon_lbl, text_lbl):
                lbl.setAttribute(Qt.WA_TransparentForMouseEvents)   # clicks go to the button
            inner.addWidget(icon_lbl)
            inner.addWidget(text_lbl, 1)
            layout.addWidget(btn)
            self.rail_items.append((btn, text_lbl, icon_lbl, icon))
        self.rail_items[0][0].clicked.connect(self.toggle_menu)
        self.screen_buttons = [self.rail_items[1][0], self.rail_items[4][0], self.rail_items[3][0], self.rail_items[2][0]]   # main, settings, skills, history: same order as self.pages
        self.rail_items[2][0].clicked.connect(lambda _checked=False: self._show_screen(3))
        self.rail_items[1][0].clicked.connect(lambda _checked=False: self._show_screen(0))
        self.rail_items[4][0].clicked.connect(lambda _checked=False: self._show_screen(1))
        self.rail_items[3][0].clicked.connect(lambda _checked=False: self._show_screen(2))
        self._paint_rail()
        self._show_screen(0)
        layout.addStretch(1)

    def _paint_rail(self):
        for btn, text_lbl, _icon, _name in self.rail_items:
            text_lbl.setVisible(self.menu_open)
            btn.setToolTip("" if self.menu_open else text_lbl.text())   # names show on hover only while collapsed

    def _paint_icons(self, active_index):
        active = self.screen_buttons[active_index]
        for btn, _text, icon_lbl, name in self.rail_items:
            icon_lbl.setPixmap(rail_icon(name, PALETTE["rail_fg"] if btn is active else PALETTE["rail_muted"]))

    def toggle_menu(self):
        self.menu_open = not self.menu_open
        self.rail.setFixedWidth(RAIL_EXPANDED_WIDTH if self.menu_open else RAIL_WIDTH)
        self._paint_rail()

    # ---------------- tasks rows ----------------
    def _refresh_tasks(self, snap=None):
        while self.tasks_layout.count():
            item = self.tasks_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        shown = None
        for a in sorted(snap or store.snapshot(), key=lambda a: a["status"] == "done"):
            done = a["status"] == "done"
            if done != shown:                 # section label: ACTIVE first, then RESOLVED
                self.tasks_layout.addWidget(self._caption("RESOLVED" if done else "ACTIVE"))
                shown = done
            self.tasks_layout.addWidget(self._task_card(a, done))
        self.tasks_layout.addStretch(1)

    def _task_card(self, a, done):
        """One action: title and percentage on top; enabled flag, progress bar and status below."""
        name = a["name"]
        st = self.task_state.get(name)
        if st is None:
            total = engine.action_total(name, a["settings"], action=a) if done else 0
            st = (total, total, "done") if done else (0, 0, None)
        steps_done, total, status = st
        if status == "done":
            pct = 1
        elif status == "skipped" or not total:
            pct = 0
        else:
            pct = min(steps_done / total, 0.99)
        colour = TASK_BAD if status == "failed" else PALETTE["muted"] if status == "skipped" else TASK_GOOD
        bar_colour = TASK_BAD if status == "failed" else PALETTE["accent"]

        card = QFrame(objectName="resolved" if done else "card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(4)

        top = QHBoxLayout()
        title = QLabel(a["info"].get("description", name), objectName="cardtitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        pct_lbl = QLabel("skipped" if status == "skipped" else f"{pct:.0%}")
        pct_lbl.setFixedWidth(70)                       # fixed width, so the title and bar never shift
        pct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pct_lbl.setStyleSheet(f"color: {colour}; font-weight: bold;")
        top.addWidget(pct_lbl)
        cl.addLayout(top)

        sub = QHBoxLayout()
        sub.setSpacing(8)
        flag = QLabel("Enabled" if a["enabled"] else "Disabled", objectName="muted")
        flag.setFixedWidth(60)                          # the same width on every card, so the bars line up
        sub.addWidget(flag)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(pct * 100))
        bar.setTextVisible(False)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {PALETTE['card_alt']}; border: 0; border-radius: 4px;"
            f" min-height: 8px; max-height: 8px; }}"
            f"QProgressBar::chunk {{ background: {bar_colour}; border-radius: 4px; }}")
        sub.addWidget(bar, 1)
        badge = QLabel("Running" if status == "running" else STATUS_TEXT.get(a["status"], "Pending"),
                       objectName="muted")
        badge.setFixedWidth(70)
        badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sub.addWidget(badge)
        cl.addLayout(sub)
        return card

    # ---------------- actions panel ----------------
    def _build_actions_panel(self):
        scroll = QScrollArea(objectName="actions")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setObjectName("actions_viewport")
        inner = QWidget(objectName="actions_inner")
        self.actions_layout = QVBoxLayout(inner)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)     # the scroll bar column provides the right gap
        self.actions_layout.setSpacing(8)
        scroll.setWidget(inner)
        self.build_actions()
        return scroll

    def build_actions(self):
        for a in store.snapshot():
            self.actions_layout.addWidget(self._action_card(a))
        self.actions_layout.addStretch(1)
        self._refresh_tasks()

    def _action_card(self, a):
        name = a["name"]
        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)

        head = QHBoxLayout()
        head.setSpacing(12)
        enabled = QCheckBox(a["info"].get("description", name))
        enabled.setCursor(Qt.PointingHandCursor)
        enabled.setChecked(a["enabled"])
        enabled.toggled.connect(lambda _c, n=name: self.save_action(n))
        head.addWidget(enabled)

        status = a["status"]
        st = QLabel(STATUS_TEXT.get(status, "Pending"))
        st.setMinimumWidth(80)                # room for the longest word, so it never shifts
        st.setStyleSheet(f"color: {STATUS_COLOUR.get(status, PALETTE['muted'])};")
        head.addWidget(st)
        self.status_vars[name] = st

        head.addStretch(1)
        head.addWidget(self._button("Run", lambda n=name: self.start(only=n)))
        cl.addLayout(head)

        grid = QGridLayout()
        grid.setContentsMargins(28, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        row = 0
        if len(engine.start_points(name)) > 1:
            label = QLabel("Start at:")
            label.setFixedWidth(130)          # same label column as the settings below
            grid.addWidget(label, row, 0)
            combo = RefreshingCombo(lambda c, n=name: self._fill_start(c, n))
            self._fill_start(combo, name)
            combo.setFixedWidth(CONTROL_WIDTH)
            grid.addWidget(combo, row, 1, Qt.AlignLeft)
            self.start_vars[name] = combo
            row += 1
        widgets = {}
        options = a["info"].get("options", {})
        dynamic = a["info"].get("dynamic_options", {})
        on_settings_page = a["info"].get("settings_page", [])
        for key, value in a["settings"].items():
            if key in on_settings_page:
                continue                      # shown on the Settings page instead
            label = QLabel(key.replace("_", " ") + ":")
            label.setFixedWidth(130)          # one column for all settings labels
            grid.addWidget(label, row, 0)
            if isinstance(value, bool):
                w = QCheckBox()
                w.setCursor(Qt.PointingHandCursor)
                w.setChecked(value)
                w.toggled.connect(lambda _c, n=name: self.save_action(n))
            elif key in dynamic:
                fn = getattr(catalog, dynamic[key])
                w = RefreshingCombo(lambda c, fn=fn: self._fill_dynamic(c, fn, c.currentText()))
                self._fill_dynamic(w, fn, str(value))
                w.setFixedWidth(CONTROL_WIDTH)
                w.currentTextChanged.connect(lambda _t, n=name: self.save_action(n))
            elif key in options:
                w = RefreshingCombo()
                w.addItems([str(o) for o in options[key]])
                w.setCurrentText(str(value))
                w.setFixedWidth(CONTROL_WIDTH)
                w.currentTextChanged.connect(lambda _t, n=name: self.save_action(n))
            else:
                w = QLineEdit(str(value))
                w.setFixedWidth(CONTROL_WIDTH)
                w.textChanged.connect(lambda _t, n=name: self.save_action(n))
            grid.addWidget(w, row, 1, Qt.AlignLeft)
            widgets[key] = w
            row += 1
        cl.addLayout(grid)

        # set last: the signals above fire while the widgets are built, and save_action ignores unknown names
        self.vars[name] = {"enabled": enabled, "settings": widgets}
        return card

    def _fill_start(self, combo, name):
        current = combo.currentText()
        combo.blockSignals(True)              # refilling must not save anything
        combo.clear()
        combo.addItems([p[0] for p in engine.start_points(name)])
        combo.setCurrentIndex(max(combo.findText(current), 0))   # falls back to "From the beginning"
        combo.blockSignals(False)

    def _fill_dynamic(self, combo, fn, current):
        items = fn() or []
        if current and current not in items:
            items.append(current)             # keep the saved value visible even if the game no longer lists it
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        combo.setCurrentIndex(max(combo.findText(current), 0))
        combo.blockSignals(False)

    def _start_at(self, only):
        if not only or only not in self.start_vars:
            return None
        chosen = self.start_vars[only].currentText()
        for label, phase, idx in engine.start_points(only):
            if label == chosen:
                return (phase, idx)
        return None

    def _value(self, w):
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QComboBox):
            return w.currentText()
        return w.text()

    def save_action(self, name):
        if name not in self.vars:
            return
        stored_action = store.action(name)
        stored = stored_action["settings"]
        widgets = self.vars[name]["settings"]
        if name in ("daily_legend_race", "team_trials"):
            ticked = [k for k in engine.ITEM_KEYS if widgets[k].isChecked()]
            if len(ticked) > engine.MAX_ITEMS:
                for k in ticked:
                    if not stored.get(k):
                        widgets[k].blockSignals(True)     # untick quietly, then save once below
                        widgets[k].setChecked(False)
                        widgets[k].blockSignals(False)
                QMessageBox.information(self, "Item limit", f"You can select at most {engine.MAX_ITEMS} items.")
        settings = {}
        for key, old in stored.items():
            if key not in widgets:            # lives on the Settings page, which saves it itself
                settings[key] = old
                continue
            raw = self._value(widgets[key])
            if isinstance(old, bool):
                settings[key] = bool(raw)
            elif isinstance(old, int):
                try:
                    settings[key] = int(raw)
                except (ValueError, TypeError):
                    settings[key] = old
            else:
                settings[key] = raw
        enabled = self.vars[name]["enabled"].isChecked()
        store.save(name, enabled, settings)
        snap = store.snapshot()
        self._refresh_tasks(snap)
        self.refresh_missing()

    def refresh_status(self):
        snap = store.snapshot()
        statuses = {a["name"]: a["status"] for a in snap}
        for name, st in self.status_vars.items():
            status = statuses.get(name, "pending")
            st.setText(STATUS_TEXT.get(status, "Pending"))
            st.setStyleSheet(f"color: {STATUS_COLOUR.get(status, PALETTE['muted'])};")
        self._refresh_tasks(snap)

    # ---------------- template capture (Tk dialog in its own process) ----------------
    def capture_template(self):
        if self.capture_proc and self.capture_proc.state() != QProcess.ProcessState.NotRunning:
            return
        # the same file launches the dialog: in the built exe sys.executable is the exe itself
        script = [] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve())]
        self.capture_proc = QProcess(self)
        self.capture_proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.capture_proc.readyReadStandardOutput.connect(self._capture_output)
        self.capture_proc.finished.connect(self._capture_done)
        self.capture_btn.setEnabled(False)
        self.log("Opening capture tool...")
        self.capture_proc.start(sys.executable, script + ["--capture", self.title_edit.text()])

    def _capture_output(self):
        text = bytes(self.capture_proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self.log(line)

    def _capture_done(self):
        self._capture_output()             # show any lines still in the pipe
        self.capture_btn.setEnabled(True)
        self.refresh_missing()             # a saved template may clear the "still needed" warning

    # ---------------- run / stop ----------------
    def start(self, only=None):
        if self.worker and self.worker.isRunning():
            return
        missing = engine.missing_templates()
        if missing and QMessageBox.question(
                self, "Missing templates",
                f"{len(missing)} template image(s) are missing, so some steps will fail.\n\nStart anyway?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.stop_event.clear()
        self.skip_event.clear()
        self.pause_event.clear()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)
        self.status_lbl.setText("Running...")
        start_at = self._start_at(only)
        self.worker = Worker(self.title_edit.text(), self.stop_event, self.skip_event,
                             self.pause_event, only, start_at)
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self._on_progress)
        self.worker.step.connect(self._on_step)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.status_lbl.setText("Stopping...")

    def skip_action(self):
        self.skip_event.set()
        self.log("Skip requested: skipping the current step...")

    def toggle_pause(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_btn.setText("Pause")
            self.status_lbl.setText("Running...")
        else:
            self.pause_event.set()
            self.pause_btn.setText("Resume")
            self.status_lbl.setText("Paused")

    def _hotkey_stop(self):
        if self.worker and self.worker.isRunning():
            self.stop_event.set()
            self.log("Stop key pressed: stopping...")

    def _on_progress(self, done, total):
        self.bar.setValue(int(done / total * 100) if total else 0)
        self.status_lbl.setText(f"Running... {done}/{total} actions finished")

    def _on_step(self, name, done, total, status):
        self.task_state[name] = (done, total, status)
        self._refresh_tasks()

    def _on_finished(self):
        for n, (d, t, s) in list(self.task_state.items()):      # a stopped run leaves no row 'running'
            if s == "running":
                self.task_state[n] = (d, t, None)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.pause_event.clear()
        self.pause_btn.setText("Pause")
        self.pause_btn.setEnabled(False)
        self.status_lbl.setText("Ready")
        self.refresh_status()
        self.refresh_missing()
        self._refresh_tasks()
        if self.pages.currentIndex() == 3:
            self._fill_history()                # a run that ended may have added rows


def main():
    app = QApplication.instance()
    load_fonts()
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    dark_title_bar(win)
    sys.exit(app.exec())


def run_capture(title):
    """Child process: the unchanged Tk capture dialog. Its log lines go to stdout for the Qt window to show."""
    import tkinter as tk
    from capture_tool import open_capture_dialog
    root = tk.Tk()
    root.withdraw()                        # the dialog is a Toplevel; the root stays hidden
    open_capture_dialog(root, title, lambda t: print(t, flush=True), lambda: None)

    def check():                           # quit once the dialog is closed (or never opened, e.g. after an error)
        if any(isinstance(w, tk.Toplevel) for w in root.winfo_children()):
            root.after(300, check)
        else:
            root.destroy()
    root.after(300, check)
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--capture":
        run_capture(sys.argv[2])
    else:
        main()