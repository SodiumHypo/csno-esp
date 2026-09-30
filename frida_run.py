"""One-shot Frida script driver (no REPL): bundle config.js, run, capture, detach.

Usage:
    python frida_run.py <script.js> <pid> [wait_seconds]

CommonJS require('./config.js') is satisfied by an inline shim, so the same
scripts run identically here and under `frida -U -p <pid> -l <script.js>`.
Prints every console.log line plus script errors, then detaches cleanly.
"""
import os
import sys
import time

import frida


def load_bundled_source(script_path):
    """Read a script and inline config.js (CommonJS shim + IIFE), so the same
    source runs under this driver and under `frida -U -l script.js`."""
    src = open(script_path, encoding="utf-8").read()
    if "require('./config.js')" not in src:
        return src
    script_dir = os.path.dirname(os.path.abspath(script_path))
    for cfg_path in (os.path.join(script_dir, "config.js"),
                     os.path.join(script_dir, "..", "phase2", "config.js")):
        if os.path.isfile(cfg_path):
            break
    else:
        raise FileNotFoundError("config.js not found near " + script_path)
    cfg = open(cfg_path, encoding="utf-8").read()
    # config.js and the script each declare top-level consts (e.g. CONFIG) that
    # would clash in one scope; the IIFE gives the script its own module scope,
    # matching what frida-compile does for the CLI path.
    return ("const module = { exports: {} };\n" + cfg +
            "\nfunction require(p) { if (p === './config.js') return module.exports; "
            "throw new Error('unknown module ' + p); }\n(function(){\n" + src + "\n})();\n")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    script_path = sys.argv[1]
    pid = int(sys.argv[2])
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0

    source = load_bundled_source(script_path)

    session = frida.get_usb_device().attach(pid)

    def on_message(message, data):
        if message.get("type") == "log":
            print(message["payload"], flush=True)
        elif message.get("type") == "error":
            print("[script-error] " + message.get("description", str(message)), flush=True)
            if message.get("stack"):
                print(message["stack"], flush=True)
        else:
            print(str(message), flush=True)

    script = session.create_script(source)
    script.on("message", on_message)
    script.load()
    time.sleep(wait)
    session.detach()
    print("[driver] detached cleanly", flush=True)


if __name__ == "__main__":
    main()
