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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frida_run import load_bundled_source

# adb executable — set ADB in the environment if not on PATH, e.g.:
#   set ADB=C:\path\to\emulator\adb.exe
ADB = os.environ.get("ADB", "adb")
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def find_emulator_client_rect():
    """(x, y, w, h) of the LDPlayer window's client area in screen coords,
    or the primary screen size as fallback."""
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def on_window(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value
            n = wt.RECT()
            user32.GetClassNameW(hwnd, buf, 256)
            if "LDPlayer" in title or "LDPlayer" in buf.value or "雷电" in title:
                if user32.GetClientRect(hwnd, ctypes.byref(n)) and n.right > 100:
                    pt = wt.POINT(0, 0)
                    if user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                        result.append((pt.x, pt.y, n.right, n.bottom))
        return True

    user32.EnumWindows(on_window, 0)
    return result[0] if result else (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def get_pid():
    if len(sys.argv) > 1:
        return int(sys.argv[1])
    out = os.popen('"' + ADB + '" shell pidof com.ledi.csno').read().strip()
    if not out:
        raise SystemExit("game not running — start it and retry")
    return int(out.split()[0])


def make_click_through(root):
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)


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

    x, y, w, h = find_emulator_client_rect()
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
        canvas.delete("all")
        if not frame.get("ok"):
            canvas.create_text(10, 10, anchor="nw", fill="orange",
                               text=f"esp: {frame.get('error', '?')}")
            return
        lt = frame.get("localTeam", -1)
        for p in frame.get("players", []):
            if p["local"]:
                color, fill = "yellow", ""
            elif p["team"] == lt:
                color, fill = "lime", ""
            else:
                color, fill = "red", "red"
            bw = max(6, int((p["fy"] - p["hy"]) * 0.45))
            x0, x1 = p["hx"] - bw // 2, p["hx"] + bw // 2
            canvas.create_rectangle(x0, p["hy"], x1, p["fy"], outline=color, width=2)
            # health bar on the left edge
            frac = max(0.0, min(1.0, p["hp"] / 100.0))
            bar_h = (p["fy"] - p["hy"]) * frac
            canvas.create_rectangle(x0 - 6, p["fy"] - bar_h, x0 - 2, p["fy"], fill=color)
            if p["spotted"]:
                canvas.create_text(x0 - 8, p["hy"] - 8, anchor="e", fill="orange", text="*")
            canvas.create_text(x0, p["fy"] + 4, anchor="nw", fill=color,
                               text=f'{p["hp"]}')
            if p["local"]:
                canvas.create_oval(p["hx"] - 2, p["hy"] - 2, p["hx"] + 2, p["hy"] + 2, fill="yellow")

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
