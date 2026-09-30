"""Phase 3 dev overlay (host-side dev aid — not the Android deliverable).

Transparent, always-on-top, click-through tkinter window pinned over the
LDPlayer window, polling the esp_loop.js RPC (~30 Hz) and drawing player boxes.

Usage:
    python esp_overlay.py [pid]     # pid auto-detected if omitted

Quit: press Enter in this console (the overlay itself is click-through).
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
import time
import tkinter as tk

import frida

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "phase2"))
from frida_run import load_bundled_source

ADB = os.environ.get("ADB", "adb")
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


# Windows whose *title* may mention LDPlayer but are not the player window
# (an Explorer folder opened at the install dir matched "LDPlayer14" and
# dragged the overlay onto itself — filter by known foreign classes).
_EXCLUDED_CLASSES = {"CabinetWClass", "ExploreWClass", "WorkerW", "Progman", "Shell_TrayWnd"}
MIN_CLIENT_W, MIN_CLIENT_H = 320, 240


def _is_emulator_window(title, cls):
    if cls in _EXCLUDED_CLASSES:
        return False
    return "LDPlayer" in cls or "LDPlayer" in title or "雷电" in title


def find_emulator_client_rect():
    """(x, y, w, h) of the LDPlayer client area in screen coords.

    Returns the largest visible, non-minimized match, or None if no usable
    player window exists right now — minimized windows report a 229x35
    @(-31996,-32000) rect, which must never be latched onto. Callers keep
    their last good geometry when this returns None.
    """
    cands = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def on_window(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value
            user32.GetClassNameW(hwnd, buf, 256)
            cls = buf.value
            if _is_emulator_window(title, cls):
                r = wt.RECT()
                if (user32.GetClientRect(hwnd, ctypes.byref(r))
                        and r.right >= MIN_CLIENT_W and r.bottom >= MIN_CLIENT_H):
                    pt = wt.POINT(0, 0)
                    if user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                        cands.append((pt.x, pt.y, r.right, r.bottom))
        return True

    user32.EnumWindows(on_window, 0)
    if not cands:
        return None
    return max(cands, key=lambda c: c[2] * c[3])


def get_pid():
    if len(sys.argv) > 1:
        return int(sys.argv[1])
    out = os.popen('"' + ADB + '" shell pidof com.ledi.csno').read().strip()
    if not out:
        raise SystemExit("game not running — start it and retry")
    return int(out.split()[0])


def overlay_hwnd(root):
    return user32.GetParent(root.winfo_id()) or root.winfo_id()


def make_click_through(root):
    style = user32.GetWindowLongW(overlay_hwnd(root), GWL_EXSTYLE)
    user32.SetWindowLongW(overlay_hwnd(root), GWL_EXSTYLE,
                          style | WS_EX_LAYERED | WS_EX_TRANSPARENT)


def keep_on_top(root):
    """Re-assert the topmost band. tk's -topmost is applied once at startup;
    a game entering/refreshing fullscreen re-raises its own window above us
    and the click-through overlay can never fight back — re-asserting every
    supervision cycle is how we always win the latest raise."""
    HWND_TOPMOST = -1
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
    user32.SetWindowPos(overlay_hwnd(root), HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


def draw_frame(canvas, frame):
    """Render one esp_loop frame (or a status message when not ok) on the canvas.

    Never leaves the canvas fully blank: the top-left line always tells the
    user which pipeline stage is live (error / attached-but-nothing-projected
    / N tracked) — a transparent overlay with zero items is indistinguishable
    from a dead one.
    """
    canvas.delete("all")
    if not frame or not frame.get("ok"):
        canvas.create_text(10, 10, anchor="nw", fill="orange",
                           text=f"esp: {(frame or {}).get('error', 'no data')}")
        return
    players = frame.get("players", [])
    if not players:
        canvas.create_text(10, 10, anchor="nw", fill="orange",
                           text="esp: attached — no players projected (menu?)")
    else:
        canvas.create_text(10, 10, anchor="nw", fill="#9aa0a6",
                           text=f"esp: {len(players)} tracked")
    lt = frame.get("localTeam", -1)
    for p in players:
        if p["local"]:
            continue  # own box carries no information — skipped by request
        color = "lime" if p["team"] == lt else "red"
        bw = max(6, int((p["fy"] - p["hy"]) * 0.45))
        x0, x1 = p["hx"] - bw // 2, p["hx"] + bw // 2
        canvas.create_rectangle(x0, p["hy"], x1, p["fy"], outline=color, width=2)
        # health bar on the left edge
        frac = max(0.0, min(1.0, p["hp"] / 100.0))
        bar_h = (p["fy"] - p["hy"]) * frac
        canvas.create_rectangle(x0 - 6, p["fy"] - bar_h, x0 - 2, p["fy"], fill=color)
        if p["spotted"]:
            canvas.create_text(x0 - 8, p["hy"] - 8, anchor="e", fill="orange", text="*")
        canvas.create_text(x0, p["fy"] + 4, anchor="nw", fill=color, text=f'{p["hp"]}')


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    pid = get_pid()
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esp_loop.js")
    source = load_bundled_source(script_path)

    session = frida.get_usb_device().attach(pid)

    def on_message(message, data):
        if message.get("type") == "error":
            print("[script-error] " + message.get("description", str(message)), flush=True)
        elif message.get("type") == "log":
            print(message["payload"], flush=True)

    script = session.create_script(source)
    script.on("message", on_message)
    script.load()
    rpc = script.exports_sync

    rect = find_emulator_client_rect()
    if rect is None:
        rect = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    x, y, w, h = rect
    print(f"[overlay] LDPlayer client: {w}x{h} @({x},{y}); pid {pid}", flush=True)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.config(bg="black")
    root.attributes("-transparentcolor", "black")
    root.geometry(f"{w}x{h}+{x}+{y}")
    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    root.update_idletasks()
    root.update()
    make_click_through(root)

    stop = threading.Event()

    def quit_on_enter():
        # With no console attached (background run), input() EOFs immediately —
        # that is NOT a quit request; only a real line quits.
        try:
            if input():
                pass
        except EOFError:
            return
        stop.set()

    threading.Thread(target=quit_on_enter, daemon=True).start()

    def draw(frame):
        draw_frame(canvas, frame)

    def tick():
        if stop.is_set():
            root.destroy()
            session.detach()
            return
        try:
            draw(rpc.get_esp_frame(w, h))
        except Exception as e:
            print("[overlay] rpc failed: %r" % e, flush=True)
        root.after(33, tick)

    # Safety quit: game process gone or runtime cap reached.
    runtime_s = float(os.environ.get("ESP_RUNTIME_S", "300"))
    started = time.time()

    def watchdog():
        if stop.is_set():
            return
        if time.time() - started > runtime_s:
            print("[overlay] runtime cap reached — quitting", flush=True)
            stop.set()
            return
        alive = os.popen('"' + ADB + '" shell pidof com.ledi.csno').read().strip()
        if not alive:
            print("[overlay] game process gone — quitting", flush=True)
            stop.set()
            return
        root.after(5000, watchdog)

    print("[overlay] running — Enter in console quits; auto-quits after "
          f"{int(runtime_s)}s or when the game exits", flush=True)
    root.after(100, tick)
    root.after(5000, watchdog)
    root.mainloop()
    print("[overlay] detached", flush=True)


if __name__ == "__main__":
    main()
