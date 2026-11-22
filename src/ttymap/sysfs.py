"""Device discovery from sysfs. No external dependencies, no root required for reads."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# A USB interface directory looks like "1-2.2:1.0" — bus-port.port:config.interface.
# This string is NOT the same as the /dev/serial/by-path fragment ("2.2"), which is
# the single most common source of udev rules that never match.
_IFACE_RE = re.compile(r"^\d+(-[\d.]+)+:\d+\.\d+$")


@dataclass
class Device:
    name: str
    sys_path: str
    kernels: str
    usb_path: str
    vid: str
    pid: str
    serial: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    interface: str | None = None
    driver: str | None = None
    symlinks: list[str] = field(default_factory=list)
    holders: list[tuple[int, str]] = field(default_factory=list)

    @property
    def dev_path(self) -> str:
        return f"/dev/{self.name}"

    @property
    def identity(self) -> str:
        return f"{self.vid}:{self.pid}"

    @property
    def has_serial(self) -> bool:
        return bool(self.serial)

    def label(self) -> str:
        """Human name: product string, falling back to driver or vid:pid."""
        return self.product or self.driver or self.identity


def _text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            value = fh.read().strip()
    except OSError:
        return None
    return value or None


def _find_interface(sys_path: str) -> str | None:
    """Walk up from the tty device until we hit the USB interface directory."""
    current = sys_path
    for _ in range(12):
        parent = os.path.dirname(current)
        if parent == current:
            return None
        if _IFACE_RE.match(os.path.basename(current)):
            return current
        current = parent
    return None


def _symlinks(devroot: str, name: str) -> list[str]:
    """/dev/serial/* entries that resolve to this device.

    Compared by basename: the udev symlinks live under /dev and resolve to
    /dev/ttyUSB0, while the device itself lives under /sys — comparing full
    real paths never matches.
    """
    found = []
    for sub in ("serial/by-id", "serial/by-path"):
        base = os.path.join(devroot, sub)
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            try:
                if os.path.basename(os.path.realpath(os.path.join(base, entry))) == name:
                    found.append(f"/dev/{sub}/{entry}")
            except OSError:
                continue
    return found


def _natural(name: str) -> tuple[str, int]:
    match = re.match(r"^(.*?)(\d+)$", name)
    if match:
        return match.group(1), int(match.group(2))
    return name, -1


def discover(root: str = "/") -> list[Device]:
    """Return every USB-backed serial port visible under ``root``."""
    sysroot = os.path.join(root, "sys")
    devroot = os.path.join(root, "dev")
    class_dir = os.path.join(sysroot, "class", "tty")
    if not os.path.isdir(class_dir):
        return []

    devices: list[Device] = []
    for name in sorted(os.listdir(class_dir), key=_natural):
        real = os.path.realpath(os.path.join(class_dir, name))
        iface = _find_interface(real)
        if iface is None:
            continue  # on-board 8250 UART, pty, console — nothing to pin
        usb = os.path.dirname(iface)
        vid = _text(os.path.join(usb, "idVendor"))
        pid = _text(os.path.join(usb, "idProduct"))
        if not vid or not pid:
            continue
        driver_link = os.path.join(iface, "driver")
        driver = os.path.basename(os.path.realpath(driver_link)) if os.path.exists(driver_link) else None
        devices.append(
            Device(
                name=name,
                sys_path=real,
                kernels=os.path.basename(iface),
                usb_path=os.path.basename(iface).split(":")[0],
                vid=vid.lower(),
                pid=pid.lower(),
                serial=_text(os.path.join(usb, "serial")),
                manufacturer=_text(os.path.join(usb, "manufacturer")),
                product=_text(os.path.join(usb, "product")),
                interface=_text(os.path.join(iface, "bInterfaceNumber")),
                driver=driver,
                symlinks=_symlinks(devroot, name),
            )
        )
    return devices


def holders(dev_path: str, procroot: str = "/proc") -> list[tuple[int, str]]:
    """Which processes currently have this tty open.

    A tty is a single queue: whoever reads a frame, the driver never sees it.
    Knowing this up front avoids "the port is silent" debugging sessions that are
    really "something else is eating the data".
    """
    try:
        target = os.path.realpath(dev_path)
    except OSError:
        return []
    found: list[tuple[int, str]] = []
    try:
        pids = os.listdir(procroot)
    except OSError:
        return []
    for pid in pids:
        if not pid.isdigit():
            continue
        fd_dir = os.path.join(procroot, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                link = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if not link.startswith("/dev/"):
                continue
            try:
                if os.path.realpath(link) != target:
                    continue
            except OSError:
                continue
            comm = _text(os.path.join(procroot, pid, "comm")) or "?"
            found.append((int(pid), comm))
            break
    return found
