"""
GameWindow: find HWND, capture screenshot, click/drag.
Windows-only (win32gui, mss, pyautogui).
"""
import time

import cv2
import mss
import numpy as np
import pyautogui
import win32con
import win32gui

from config import REF_HEIGHT


class GameNotFound(Exception):
    pass


class FocusFailed(Exception):
    """The game window could not be brought to the front, so no input was sent."""
    pass


class GameWindow:
    def __init__(self, title_part):
        self.title_part = title_part.strip().lower()
        self._hwnd = None
        self.hwnd()

    def hwnd(self):
        if self._hwnd and win32gui.IsWindow(self._hwnd) and win32gui.IsWindowVisible(self._hwnd):
            return self._hwnd
        matches = []

        def visit(h, _):
            if win32gui.IsWindowVisible(h):
                title = win32gui.GetWindowText(h)
                if title and self.title_part in title.lower():
                    try:
                        _, _, w, ht = win32gui.GetClientRect(h)
                        matches.append((w * ht, h))
                    except Exception:
                        pass

        win32gui.EnumWindows(visit, None)
        matches = [m for m in matches if m[0] > 300 * 300]
        if not matches:
            raise GameNotFound(f"No visible window with '{self.title_part}' in its title. "
                               "Open the game (not minimised) or fix the window title.")
        self._hwnd = max(matches)[1]
        return self._hwnd

    def client_rect(self):
        h = self.hwnd()
        l, t = win32gui.ClientToScreen(h, (0, 0))
        _, _, w, ht = win32gui.GetClientRect(h)
        return l, t, w, ht

    def focus(self):
        """Bring the game to the front. Raises FocusFailed if it is not in front afterwards,
        so a click or drag is never sent into another app."""
        h = self.hwnd()
        if win32gui.IsIconic(h):
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
            time.sleep(0.3)
        if win32gui.GetForegroundWindow() == h:
            return
        for _ in range(2):
            try:
                pyautogui.press("alt")
                win32gui.SetForegroundWindow(h)
            except Exception:
                pass  # Windows may refuse; the check below decides
            time.sleep(0.3)
            if win32gui.GetForegroundWindow() == h:
                return
        raise FocusFailed("Could not bring the game window to the front, so nothing was clicked. "
                          "Click the game window once, then try again.")

    def screenshot(self):
        self.focus()
        l, t, w, h = self.client_rect()
        with mss.mss() as sct:
            raw = np.array(sct.grab({"left": l, "top": t, "width": w, "height": h}))
        img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        f = REF_HEIGHT / h
        return cv2.resize(img, (max(1, round(w * f)), REF_HEIGHT))

    def drag(self, x1, y1, x2, y2, duration=0.5):
        self.focus()
        l, t, _, h = self.client_rect()
        f = h / REF_HEIGHT
        pyautogui.moveTo(int(l + x1 * f), int(t + y1 * f))
        time.sleep(0.1)
        pyautogui.mouseDown()
        try:
            time.sleep(0.1)
            pyautogui.moveTo(int(l + x2 * f), int(t + y2 * f), duration=duration)
            time.sleep(0.1)
        finally:
            pyautogui.mouseUp()

    def tap(self, x, y):
        self.focus()
        l, t, _, h = self.client_rect()
        f = h / REF_HEIGHT
        px, py = int(l + x * f), int(t + y * f)
        pyautogui.moveTo(px, py)
        time.sleep(0.05)
        pyautogui.click()
