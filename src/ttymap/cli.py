"""Command line interface."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import sys

from . import __version__, demo
from .config import Alias, Config, ConfigError, resolve
from .report import shorten, table
from .rules import PlanEntry, apply_rules, plan, render, rules_path, verify
from .sysfs import Device, discover, holders

OK, FAIL, USAGE = 0, 1, 2


def _load_devices(args) -> tuple[list[Device], str]:
    root = "/"
    if args.demo:
        root = demo.build()
        atexit.register(shutil.rmtree, root, True)
    elif getattr(args, "root", None):
        root = args.root
    devices = discover(root)
    if root == "/":
        for device in devices:
            device.holders = holders(device.dev_path)
    return devices, root


def _load_config(args) -> Config:
    return Config.load(resolve(getattr(args, "config", None)))


def _devroot(root: str) -> str:
    return os.path.join(root, "dev")


def cmd_scan(args) -> int:
    devices, _root = _load_devices(args)
    if args.json:
        print(json.dumps(
            [
                {
                    "port": d.dev_path,
                    "vid_pid": d.identity,
                    "serial": d.serial,
                    "product": d.product,
                    "manufacturer": d.manufacturer,
                    "kernels": d.kernels,
                    "usb_path": d.usb_path,
                    "driver": d.driver,
                    "symlinks": d.symlinks,
                    "holders": [f"{comm}({pid})" for pid, comm in d.holders],
                }
                for d in devices
            ],
            indent=2,
        ))
        return OK
    if not devices:
        print("No USB serial devices found.")
        print("  Check: ls -l /dev/serial/by-id/ /dev/ttyUSB*")
        return FAIL
    rows = []
    for device in devices:
        held = ", ".join(f"{comm}({pid})" for pid, comm in device.holders) or "-"
        rows.append([
            device.name,
            device.identity,
            shorten(device.serial, 22),
            shorten(device.product, 38),
            device.kernels,
            held,
        ])
    print(table(["PORT", "VID:PID", "SERIAL", "PRODUCT", "KERNELS", "HELD BY"], rows))
    print()
    missing = [d.name for d in devices if not d.has_serial]
    if missing:
        print(f"  {len(missing)} device(s) report no USB serial number: {', '.join(missing)}")
        print("  These cannot be identified by identity — pin them to a physical port")
        print("  (match = \"port\") so the name stays put when other devices come and go.")
    return OK


def cmd_init(args) -> int:
    devices, _root = _load_devices(args)
    if not devices:
        print("No devices to describe.", file=sys.stderr)
        return FAIL
    print("# ttymap config — generated from the devices attached right now.")
    print("# Rename each alias to whatever your launch files / drivers expect,")
    print("# then run: ttymap plan")
    print()
    for index, device in enumerate(devices):
        name = f"ttyDev{index}"
        print(f"# {device.name}  {device.identity}  {device.product or '?'}")
        print(f"[aliases.{name}]")
        if device.has_serial:
            print('match  = "usb"')
            print(f'vid    = "{device.vid}"')
            print(f'pid    = "{device.pid}"')
            print(f'serial = "{device.serial}"')
        else:
            print('match   = "port"')
            print(f'kernels = "{device.kernels}"')
            print("# no USB serial number: bound to this physical port on purpose")
        print()
    return OK


def _print_plan(entries: list[PlanEntry], config: Config) -> None:
    rows = [[e.alias.name, e.alias.describe(), e.status()] for e in entries]
    print(table(["ALIAS", "MATCH", "RESULT"], rows))
    print()
    print(render(entries, config))


def cmd_plan(args) -> int:
    config = _load_config(args)
    devices, _root = _load_devices(args)
    entries = plan(config, devices)
    _print_plan(entries, config)
    bad = [e for e in entries if not e.ok]
    if bad:
        print(f"{len(bad)} alias(es) cannot be resolved. Fix those before applying.", file=sys.stderr)
        return FAIL
    return OK


def cmd_apply(args) -> int:
    config = _load_config(args)
    devices, root = _load_devices(args)
    entries = plan(config, devices)
    bad = [e for e in entries if not e.ok]
    if bad:
        _print_plan(entries, config)
        print(f"Refusing to write rules: {len(bad)} alias(es) unresolved.", file=sys.stderr)
        return FAIL
    text = render(entries, config)
    path = rules_path(root)
    if args.dry_run:
        print(f"# would write {path}")
        print(text)
        return OK
    if root != "/":
        print("--root is read-only for writes; use --dry-run to preview.", file=sys.stderr)
        return USAGE
    if os.geteuid() != 0:
        print("Writing udev rules requires root. Re-run with sudo.", file=sys.stderr)
        return USAGE
    try:
        written, backup = apply_rules(entries, config, root=root, force=args.force)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return FAIL
    print(f"wrote {written}")
    if backup:
        print(f"backup {backup}")
    checks = verify(config, devices, devroot=_devroot(root))
    failed = [c for c in checks if not c.ok]
    for check in checks:
        print(f"  {'ok  ' if check.ok else 'FAIL'}  {check.alias}: {check.message}")
    if failed:
        print()
        print(f"{len(failed)} alias(es) did not resolve after reload.", file=sys.stderr)
        print("The rules file is in place; re-run 'ttymap verify' after the device settles.",
              file=sys.stderr)
        return FAIL
    return OK


def cmd_verify(args) -> int:
    config = _load_config(args)
    devices, root = _load_devices(args)
    checks = verify(config, devices, devroot=_devroot(root))
    if args.json:
        print(json.dumps([{"alias": c.alias, "ok": c.ok, "message": c.message} for c in checks], indent=2))
    else:
        for check in checks:
            print(f"  {'ok  ' if check.ok else 'FAIL'}  {check.alias}: {check.message}")
    return OK if all(c.ok for c in checks) else FAIL


def cmd_doctor(args) -> int:
    config = _load_config(args)
    devices, root = _load_devices(args)
    problems = 0
    print(f"config: {config.path}  ({len(config.aliases)} aliases)")
    print(f"devices: {len(devices)} USB serial port(s)")

    no_serial = [d for d in devices if not d.has_serial]
    if no_serial:
        print()
        print("Devices without a USB serial number:")
        for device in no_serial:
            alias = next((a for a in config.aliases if a.match == "port" and a.kernels == device.kernels), None)
            tag = f"pinned as {alias.name}" if alias else "NOT pinned"
            print(f"  {device.name}  {device.identity}  {device.kernels}  {tag}")
            if alias is None:
                problems += 1

    print()
    print("Alias resolution:")
    for entry in plan(config, devices):
        mark = "ok  " if entry.ok else "FAIL"
        if not entry.ok:
            problems += 1
        print(f"  {mark}  {entry.alias.name}: {entry.status()}")

    busy = [d for d in devices if d.holders]
    if busy:
        print()
        print("Ports currently open by another process:")
        for device in busy:
            who = ", ".join(f"{comm}({pid})" for pid, comm in device.holders)
            print(f"  {device.name}: {who}")
        print("  A tty is a single queue — anything you read, the driver never sees.")

    path = rules_path(root)
    print()
    if os.path.isfile(path):
        print(f"rules: {path} (present)")
    else:
        print(f"rules: {path} missing — run 'ttymap apply'")
        problems += 1

    checks = verify(config, devices, devroot=_devroot(root))
    stale = [c for c in checks if not c.ok]
    if stale:
        print()
        print("Aliases that do not currently resolve:")
        for check in stale:
            print(f"  {check.alias}: {check.message}")
        problems += len(stale)

    print()
    print("no problems found" if problems == 0 else f"{problems} problem(s) found")
    return OK if problems == 0 else FAIL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ttymap",
        description="Stable names for USB serial devices on Linux.",
    )
    parser.add_argument("--version", action="version", version=f"ttymap {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, config_required=True):
        p.add_argument("-c", "--config", help="path to ttymap.toml")
        p.add_argument("--root", help="alternate filesystem root (read-only, for testing)")
        p.add_argument("--demo", action="store_true", help="use a synthetic device tree instead of hardware")
        return p

    p = common(sub.add_parser("scan", help="list USB serial ports and what they are"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = common(sub.add_parser("init", help="print a config skeleton for the attached devices"))
    p.set_defaults(func=cmd_init)

    p = common(sub.add_parser("plan", help="show the rules that would be written"))
    p.set_defaults(func=cmd_plan)

    p = common(sub.add_parser("apply", help="write the udev rules and verify them"))
    p.add_argument("--dry-run", action="store_true", help="print instead of writing")
    p.add_argument("--force", action="store_true", help="overwrite a rules file ttymap did not write")
    p.set_defaults(func=cmd_apply)

    p = common(sub.add_parser("verify", help="check every alias points at the right device"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = common(sub.add_parser("doctor", help="one-shot health check"))
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return USAGE


if __name__ == "__main__":
    sys.exit(main())
