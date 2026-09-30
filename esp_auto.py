"""Automated ESP supervisor — zero manual steps, self-healing.

Every 2 s it checks, in order:
  1. emulator (adb device state)        → wait if offline
  2. frida-server on the device         → (re)started if dead
  3. game process (com.ledi.csno pid)   → attach on new pid, detach on exit
  4. emulator window rect               → overlay repositioned if it moved

While attached, the esp_loop RPC is polled at ~30 Hz and drawn on the same
transparent click-through overlay as esp_overlay.py.

Usage:
    python esp_auto.py            # runs until Enter in console (or ESP_RUNTIME_S)

Environment:
    ADB             adb executable if not on PATH
    ESP_RUNTIME_S   auto-quit after N seconds (0 = unlimited, default)
"""
import os
import subprocess
import sys
import threading
import time
import tkinter as tk

import frida

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esp_overlay import find_emulator_client_rect, make_click_through, draw_frame
from frida_run import load_bundled_source

ADB = os.environ.get("ADB", "adb")
PKG = "com.ledi.csno"
FRIDA_BIN = "/data/local/tmp/frida-server-x64"
FRIDA_LOG = "/data/local/tmp/fs-x64.log"
CHECK_MS = 2000       # supervision cadence
POLL_MS = 33          # ESP frame cadence (~30 Hz)
RPC_FAIL_LIMIT = 30   # ~1 s of consecutive RPC failures -> forced re-attach
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esp_loop.js")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class EspAuto:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.config(bg="black")
        self.root.attributes("-transparentcolor", "black")
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.w, self.h, self.rect = self.place_over_emulator()
        self.root.update()
        make_click_through(self.root)

        self.session = None
        self.script = None
        self.rpc = None
        self.pid = None
        self.rpc_fails = 0
        self.status = "starting"
        self.stop = False
        self.started = time.time()
        self.runtime_s = float(os.environ.get("ESP_RUNTIME_S", "0"))

        threading.Thread(target=self._quit_on_enter, daemon=True).start()
        self.root.after(200, self.supervise)
        self.root.after(100, self.tick)

    # ---------- infrastructure checks ----------

    def adb(self, *args):
        try:
            r = subprocess.run([ADB, *args], capture_output=True, timeout=15)
            return r.stdout.decode("utf-8", "replace").strip()
        except Exception:
            return ""

    def device_online(self):
        return self.adb("get-state") == "device"

    def ensure_frida_server(self):
        if self.adb("shell", "pidof frida-server-x64"):
            return
        self.adb("shell", "su -c 'setsid " + FRIDA_BIN + " > " + FRIDA_LOG + " 2>&1 < /dev/null &'")
        time.sleep(0.5)
        if self.adb("shell", "pidof frida-server-x64"):
            log("frida-server (re)started")
        else:
            self.status = "frida-server failed to start"

    def game_pid(self):
        out = self.adb("shell", "pidof", PKG)
        try:
            return int(out.split()[0]) if out else None
        except ValueError:
            return None

    # ---------- frida session lifecycle ----------

    def on_message(self, message, data):
        if message.get("type") == "error":
            log("[script-error] " + message.get("description", str(message)))
        elif message.get("type") == "log":
            log(message["payload"])

    def on_detached(self, reason, *args):
        log(f"session detached ({reason})")
        self.pid = None
        self.rpc = None
        self.session = None
        self.script = None

    def attach(self, pid):
        self.detach()
        try:
            device = frida.get_usb_device()
            session = device.attach(pid)
            script = session.create_script(load_bundled_source(SCRIPT_PATH))
            script.on("message", self.on_message)
            script.load()
            session.on("detached", self.on_detached)
            self.session, self.script, self.rpc = session, script, script.exports_sync
            self.pid = pid
            self.rpc_fails = 0
            log(f"attached to {PKG} pid {pid}")
        except Exception as e:
            self.status = f"attach failed: {e}"
            log(f"attach failed: {e!r}")
            self.detach()

    def detach(self):
        for attr in ("rpc", "script", "session"):
            setattr(self, attr, None)
        self.pid = None
        if self.session:
            try:
                self.session.detach()
            except Exception:
                pass
            self.session = None

    # ---------- overlay geometry ----------

    def place_over_emulator(self):
        x, y, w, h = find_emulator_client_rect()
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        return w, h, (x, y, w, h)

    def refresh_geometry(self):
        rect = find_emulator_client_rect()
        if rect != self.rect:
            self.rect = rect
            x, y, w, h = rect
            self.root.geometry(f"{w}x{h}+{x}+{y}")
            self.w, self.h = w, h
            log(f"overlay repositioned: {w}x{h} @({x},{y})")

    # ---------- loops ----------

    def supervise(self):
        if self.stop:
            return
        try:
            if not self.device_online():
                if self.pid is not None:
                    log("emulator offline — detaching")
                self.detach()
                self.status = "waiting for emulator..."
            else:
                self.ensure_frida_server()
                pid = self.game_pid()
                if pid is None:
                    if self.pid is not None:
                        log("game exited")
                    self.detach()
                    self.status = "waiting for game..."
                elif pid != self.pid:
                    self.attach(pid)
                else:
                    self.refresh_geometry()
            if self.runtime_s > 0 and time.time() - self.started > self.runtime_s:
                log("runtime cap reached — quitting")
                self.stop = True
        except Exception as e:
            self.status = f"supervise error: {e}"
            log(f"supervise error: {e!r}")
        self.root.after(CHECK_MS, self.supervise)

    def tick(self):
        if self.stop:
            self.root.destroy()
            self.detach()
            return
        if self.rpc is not None:
            try:
                frame = self.rpc.get_esp_frame(self.w, self.h)
                self.rpc_fails = 0
            except Exception as e:
                self.rpc_fails += 1
                if self.rpc_fails >= RPC_FAIL_LIMIT:
                    log(f"rpc failed {self.rpc_fails}x — forcing re-attach")
                    self.detach()
                frame = {"ok": False, "error": f"rpc error ({e})"}
        else:
            frame = {"ok": False, "error": self.status}
        draw_frame(self.canvas, frame)
        self.root.after(POLL_MS, self.tick)

    # ---------- control ----------

    def _quit_on_enter(self):
        # With no console attached, input() EOFs immediately — that is NOT a
        # quit request; only a real line quits.
        try:
            input()
        except EOFError:
            return
        self.stop = True

    def run(self):
        log("supervisor running — Enter in console quits")
        self.root.mainloop()
        self.detach()
        log("stopped")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    EspAuto().run()


if __name__ == "__main__":
    main()
