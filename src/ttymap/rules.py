"""Bind aliases to devices, render udev rules, apply them, and prove they worked."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from .config import Alias, Config
from .sysfs import Device

RULES_DIR = "/etc/udev/rules.d"
RULES_NAME = "99-ttymap.rules"
MARKER = "# managed by ttymap — edits are overwritten on the next 'ttymap apply'"


@dataclass
class PlanEntry:
    alias: Alias
    device: Device | None = None
    conflict: str | None = None

    @property
    def ok(self) -> bool:
        return self.device is not None and self.conflict is None

    def status(self) -> str:
        if self.conflict:
            return f"CONFLICT: {self.conflict}"
        if self.device is None:
            return "no matching device"
        return f"-> {self.device.name} ({self.device.kernels})"


def matches(alias: Alias, device: Device) -> bool:
    if alias.match == "port":
        return device.kernels == alias.kernels
    if device.vid != alias.vid or device.pid != alias.pid:
        return False
    if alias.serial and device.serial != alias.serial:
        return False
    return True


def plan(config: Config, devices: list[Device]) -> list[PlanEntry]:
    entries: list[PlanEntry] = []
    claimed: dict[str, str] = {}
    for alias in config.aliases:
        hits = [d for d in devices if matches(alias, d)]
        entry = PlanEntry(alias=alias)
        if len(hits) > 1:
            names = ", ".join(d.name for d in hits)
            entry.conflict = f"matches {len(hits)} devices ({names}) — add 'serial' or use match='port'"
        elif hits:
            device = hits[0]
            if device.name in claimed:
                entry.conflict = f"{device.name} already claimed by '{claimed[device.name]}'"
            else:
                claimed[device.name] = alias.name
                entry.device = device
        entries.append(entry)
    return entries


def render(entries: list[PlanEntry], config: Config) -> str:
    lines = [
        MARKER,
        "#",
        "# Regenerate with: ttymap apply",
        "# Verify with:     ttymap verify",
        "",
    ]
    if config.path:
        lines.insert(2, f"# Source: {config.path}")
    for entry in entries:
        lines.append(f"# {entry.alias.name}: {entry.alias.describe()}")
        lines.append(entry.alias.rule())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def rules_path(root: str = "/") -> str:
    return os.path.join(root, RULES_DIR.lstrip("/"), RULES_NAME)


def _needs_root() -> bool:
    return os.geteuid() != 0


def write_rules(entries: list[PlanEntry], config: Config, root: str = "/", force: bool = False) -> tuple[str, str | None]:
    """Write the rules file, backing up anything it replaces. Returns (path, backup)."""
    path = rules_path(root)
    backup = None
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            existing = fh.read()
        if MARKER not in existing and not force:
            raise RuntimeError(
                f"{path} exists and was not written by ttymap; refusing to overwrite "
                "(re-run with --force, or move it aside)"
            )
        backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, backup)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(entries, config))
    return path, backup


def reload_rules(root: str = "/") -> None:
    if root != "/":
        return
    for cmd in (
        ["udevadm", "control", "--reload-rules"],
        ["udevadm", "trigger", "--subsystem-match=tty"],
        ["udevadm", "settle", "--timeout=10"],
    ):
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return


def apply_rules(entries: list[PlanEntry], config: Config, root: str = "/", force: bool = False) -> tuple[str, str | None]:
    """Write the rules, then ask udev to reload them."""
    path, backup = write_rules(entries, config, root=root, force=force)
    reload_rules(root)
    return path, backup


@dataclass
class Check:
    alias: str
    ok: bool
    message: str


def verify(config: Config, devices: list[Device], devroot: str = "/dev") -> list[Check]:
    """Prove every alias resolves to a device that still matches its config."""
    by_name = {d.name: d for d in devices}
    checks: list[Check] = []
    for alias in config.aliases:
        link = os.path.join(devroot, alias.name)
        if not os.path.lexists(link):
            checks.append(Check(alias.name, False, "symlink missing — rules not loaded, or no device present"))
            continue
        target = os.path.basename(os.path.realpath(link))
        device = by_name.get(target)
        if device is None:
            checks.append(Check(alias.name, False, f"points at {target}, which is not a known USB serial port"))
            continue
        if not matches(alias, device):
            checks.append(
                Check(
                    alias.name,
                    False,
                    f"points at {target} ({device.kernels}) which does not match {alias.describe()}",
                )
            )
            continue
        checks.append(Check(alias.name, True, f"-> {target} ({device.kernels})"))
    return checks
