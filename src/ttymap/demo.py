"""A synthetic /sys + /dev tree, so the tool can be tried (and tested) without hardware.

Every claim in the README can be reproduced with ``ttymap scan --demo``.
"""

from __future__ import annotations

import os
import tempfile

# (tty name, vid, pid, serial, manufacturer, product, usb port, driver)
DEVICES = [
    ("ttyUSB0", "1a86", "7523", None, "wch.cn", "USB2.0-Serial", "1-2.2", "ch341-uart"),
    ("ttyUSB1", "10c4", "ea60", "0001", "Silicon Labs", "CP2102 USB to UART Bridge Controller", "1-2.3", "cp210x"),
    ("ttyUSB2", "0403", "6001", "A10KZ9PQ", "FTDI", "FT232R USB UART", "1-2.4", "ftdi_sio"),
    ("ttyACM0", "2341", "0043", "85434233353751F0E1E1", "Arduino", "Arduino Uno", "1-3", "cdc_acm"),
]

ROOT = "sys/devices/pci0000:00/0000:00:14.0/usb1"


def _write(path: str, text: str = "") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _link(target: str, link: str) -> None:
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if os.path.lexists(link):
        os.unlink(link)
    try:
        os.symlink(target, link)
    except OSError:
        pass


def build(base: str | None = None) -> str:
    """Create the fake tree and return its root."""
    base = base or tempfile.mkdtemp(prefix="ttymap-demo-")
    for name, vid, pid, serial, manufacturer, product, port, driver in DEVICES:
        usb = os.path.join(base, ROOT, port)
        iface = os.path.join(usb, f"{port}:1.0")
        _write(os.path.join(usb, "idVendor"), vid + "\n")
        _write(os.path.join(usb, "idProduct"), pid + "\n")
        _write(os.path.join(usb, "manufacturer"), manufacturer + "\n")
        _write(os.path.join(usb, "product"), product + "\n")
        if serial:
            _write(os.path.join(usb, "serial"), serial + "\n")
        _write(os.path.join(iface, "bInterfaceNumber"), "00\n")
        os.makedirs(os.path.join(base, "sys/bus/usb/drivers", driver), exist_ok=True)
        _link("../../../../../../bus/usb/drivers/" + driver, os.path.join(iface, "driver"))

        # /sys/class/tty/<name> -> ..../<iface>/<name>/tty/<name>
        ttydir = os.path.join(iface, name, "tty", name)
        os.makedirs(ttydir, exist_ok=True)
        class_dir = os.path.join(base, "sys/class/tty")
        _link(os.path.relpath(ttydir, class_dir), os.path.join(class_dir, name))

        _write(os.path.join(base, "dev", name))
        ident = f"{manufacturer}_{product}_{serial or 'noserial'}-if00-port0".replace("/", "_")
        _link(os.path.join("..", "..", name), os.path.join(base, "dev/serial/by-id", f"usb-{ident}"))
        _link(os.path.join("..", "..", name),
              os.path.join(base, "dev/serial/by-path", f"pci-0000:00:14.0-usb-0:{port.split('-')[1]}:1.0-port0"))
    return base
