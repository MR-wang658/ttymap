"""Config loading: TOML when the interpreter has it, a small built-in parser otherwise.

Python 3.10 (Ubuntu 22.04 / ROS 2 Humble) has no ``tomllib``. Rather than pulling in a
dependency just to read a dozen lines of config, we ship a parser for the subset we use:
tables, string/integer values, and comments.
"""

from __future__ import annotations

import os
import re
from typing import Any

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 only
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _toml = None

VALID_MATCH = ("usb", "port")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ConfigError(Exception):
    pass


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw, 0)
    except ValueError:
        return raw


def _mini_parse(text: str) -> dict[str, Any]:
    """Parse the flat TOML subset used by ttymap configs."""
    root: dict[str, Any] = {}
    current = root
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.split("#", 1)[0].strip() if not line.lstrip().startswith("#") else ""
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            target = root
            for part in stripped[1:-1].split("."):
                part = part.strip()
                if not part:
                    raise ConfigError(f"line {lineno}: empty table name")
                target = target.setdefault(part, {})
                if not isinstance(target, dict):
                    raise ConfigError(f"line {lineno}: '{part}' is both a key and a table")
            current = target
            continue
        if "=" not in stripped:
            raise ConfigError(f"line {lineno}: expected 'key = value'")
        key, value = stripped.split("=", 1)
        current[key.strip()] = _parse_value(value)
    return root


class Alias:
    __slots__ = ("name", "match", "vid", "pid", "serial", "kernels", "mode", "group")

    def __init__(self, name: str, spec: dict[str, Any]):
        self.name = name
        self.match = str(spec.get("match", "usb")).lower()
        self.vid = str(spec["vid"]).lower() if "vid" in spec else None
        self.pid = str(spec["pid"]).lower() if "pid" in spec else None
        self.serial = str(spec["serial"]) if spec.get("serial") else None
        self.kernels = str(spec["kernels"]) if "kernels" in spec else None
        self.mode = str(spec["mode"]) if "mode" in spec else None
        self.group = str(spec["group"]) if "group" in spec else None
        self.validate()

    def validate(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ConfigError(f"alias {self.name!r}: only letters, digits, '_', '.', '-' allowed")
        if self.match not in VALID_MATCH:
            raise ConfigError(f"alias {self.name!r}: match must be one of {VALID_MATCH}")
        if self.match == "usb":
            if not self.vid or not self.pid:
                raise ConfigError(f"alias {self.name!r}: match='usb' needs vid and pid")
        else:
            if not self.kernels:
                raise ConfigError(f"alias {self.name!r}: match='port' needs kernels")
            if not re.match(r"^\d+(-[\d.]+)+:\d+\.\d+$", self.kernels):
                raise ConfigError(
                    f"alias {self.name!r}: kernels={self.kernels!r} is not a USB interface id "
                    "(expected something like '1-2.2:1.0')"
                )

    @property
    def specificity(self) -> int:
        if self.match == "port":
            return 3
        return 3 if self.serial else 2

    def rule(self) -> str:
        parts = ['SUBSYSTEM=="tty"']
        if self.match == "usb":
            parts.append(f'ATTRS{{idVendor}}=="{self.vid}"')
            parts.append(f'ATTRS{{idProduct}}=="{self.pid}"')
            if self.serial:
                parts.append(f'ATTRS{{serial}}=="{self.serial}"')
        else:
            parts.append(f'KERNELS=="{self.kernels}"')
        if self.mode:
            parts.append(f'MODE="{self.mode}"')
        if self.group:
            parts.append(f'GROUP="{self.group}"')
        parts.append(f'SYMLINK+="{self.name}"')
        return ", ".join(parts)

    def describe(self) -> str:
        if self.match == "port":
            return f"port {self.kernels}"
        base = f"{self.vid}:{self.pid}"
        return f"{base} serial={self.serial}" if self.serial else f"{base} (any serial)"


class Config:
    def __init__(self, aliases: list[Alias], path: str | None = None):
        self.aliases = aliases
        self.path = path

    @classmethod
    def load(cls, path: str) -> "Config":
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise ConfigError(f"cannot read {path}: {exc}") from exc
        if _toml is not None:
            try:
                data = _toml.loads(text)
            except Exception as exc:  # noqa: BLE001 - surface any parser error verbatim
                raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
        else:
            data = _mini_parse(text)
        table = data.get("aliases")
        if not isinstance(table, dict) or not table:
            raise ConfigError(f"{path}: no [aliases.<name>] tables found")
        aliases = []
        for name, spec in table.items():
            if not isinstance(spec, dict):
                raise ConfigError(f"{path}: [aliases.{name}] must be a table")
            aliases.append(Alias(name, spec))
        return cls(aliases, path=path)

    def find(self, name: str) -> Alias | None:
        for alias in self.aliases:
            if alias.name == name:
                return alias
        return None


def resolve(path: str | None) -> str:
    """Locate the config file, defaulting to the current directory."""
    if path:
        if os.path.isfile(path):
            return path
        raise ConfigError(f"cannot read {path}: no such file")
    for candidate in ("ttymap.toml", os.path.expanduser("~/.config/ttymap.toml")):
        if os.path.isfile(candidate):
            return candidate
    raise ConfigError(
        "no config found. Create ttymap.toml (run 'ttymap init' to generate one, "
        "or see examples/ttymap.toml)"
    )
