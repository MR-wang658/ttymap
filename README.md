# ttymap

**Stable, readable names for USB serial devices on Linux.**

![ci](https://github.com/OWNER/ttymap/actions/workflows/ci.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

`/dev/ttyUSB0` becomes `/dev/ttyArm`. It stays `/dev/ttyArm` after a reboot, after you plug
in a different device, and after the kernel renumbers everything.

```
$ ls /dev/ttyUSB*
/dev/ttyUSB0  /dev/ttyUSB1  /dev/ttyUSB2

# yesterday the arm was ttyUSB1. today it is ttyUSB0.
# your launch file says ttyUSB1. the robot moves the wrong joint.
```

---

## What it does

- **Scans** every USB serial port and tells you what each one actually is (vid:pid, serial
  number, product string, driver, physical port, and which process has it open).
- **Generates** udev rules from a small config file, and **verifies** afterwards that every
  symlink resolves to a device that still matches its config.
- **Refuses** to do the three things that make udev debugging miserable: silently overwrite
  your existing rules, write partial rules, or report success without checking.

No dependencies. No root needed to inspect anything. Python 3.10+.

## Install

```bash
git clone https://github.com/OWNER/ttymap && cd ttymap
pipx install .          # or: pip install --user .
```

Working from a checkout instead:

```bash
PYTHONPATH=src python3 -m ttymap scan
```

## Demo

No serial hardware required — `--demo` builds a synthetic `/sys` + `/dev` tree in a temp
directory and runs the whole flow against it:

```bash
ttymap scan --demo
ttymap plan --demo -c examples/ttymap.toml
ttymap doctor --demo -c examples/ttymap.toml
```

<!-- recording goes here: docs/demo.mp4 (under 5 MB plays inline on GitHub) -->
<!-- ![demo](docs/demo.mp4) -->

To record it: GNOME on Wayland has a built-in recorder (`Ctrl+Alt+Shift+R`, saves webm to
`~/Videos`); on X11 use `peek`. Convert either to mp4 before committing:

```bash
ffmpeg -i input.webm -vf "fps=15,scale=1280:-1" -pix_fmt yuv420p docs/demo.mp4
```

## Quickstart

```bash
ttymap scan                              # what is plugged in?
ttymap init > ttymap.toml                # skeleton config, one block per device
$EDITOR ttymap.toml                      # rename ttyDev0 -> ttyArm, etc.
ttymap plan                              # rules that would be written (no changes)
sudo ttymap apply                        # write, reload, verify
ttymap doctor                            # one-shot health check
```

`ttymap scan` on four attached devices:

```
  PORT     VID:PID    SERIAL                PRODUCT                               KERNELS    HELD BY
  -------  ---------  --------------------  ------------------------------------  ---------  -------
  ttyACM0  2341:0043  85434233353751F0E1E1  Arduino Uno                           1-3:1.0    -
  ttyUSB0  1a86:7523  -                     USB2.0-Serial                         1-2.2:1.0  -
  ttyUSB1  10c4:ea60  0001                  CP2102 USB to UART Bridge Controller  1-2.3:1.0  -
  ttyUSB2  0403:6001  A10KZ9PQ              FT232R USB UART                       1-2.4:1.0  -

  1 device(s) report no USB serial number: ttyUSB0
  These cannot be identified by identity — pin them to a physical port
  (match = "port") so the name stays put when other devices come and go.
```

`ttymap plan` shows both the binding and the rules it would write:

```
  ALIAS       MATCH                                  RESULT
  ----------  -------------------------------------  ----------------------
  ttyArm      port 1-2.2:1.0                         -> ttyUSB0 (1-2.2:1.0)
  ttyChassis  10c4:ea60 serial=0001                  -> ttyUSB1 (1-2.3:1.0)
  ttyLidar    0403:6001 serial=A10KZ9PQ              -> ttyUSB2 (1-2.4:1.0)
  ttyAux      2341:0043 serial=85434233353751F0E1E1  -> ttyACM0 (1-3:1.0)

# managed by ttymap — edits are overwritten on the next 'ttymap apply'
#
# Source: ttymap.toml
# Regenerate with: ttymap apply
# Verify with:     ttymap verify

# ttyArm: port 1-2.2:1.0
SUBSYSTEM=="tty", KERNELS=="1-2.2:1.0", MODE="0666", SYMLINK+="ttyArm"

# ttyLidar: 0403:6001 serial=A10KZ9PQ
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A10KZ9PQ", SYMLINK+="ttyLidar"
```

After `apply`, `verify` re-resolves every symlink and checks it against the config — not just
that the link exists:

```
  ok    ttyArm: -> ttyUSB0 (1-2.2:1.0)
  ok    ttyChassis: -> ttyUSB1 (1-2.3:1.0)
  ok    ttyLidar: -> ttyUSB2 (1-2.4:1.0)
  ok    ttyAux: -> ttyACM0 (1-3:1.0)
```

## Why not just write the udev rule by hand?

You can, and most people do, and then they spend an afternoon on one of these two traps.

### Trap 1 — the `by-path` fragment is not `KERNELS`

`/dev/serial/by-path` gives you this:

```
pci-0000:00:14.0-usb-0:2.2:1.0-port0
```

The natural move is to copy `2.2` into a rule:

```udev
SUBSYSTEM=="tty", KERNELS=="2.2", SYMLINK+="ttyArm"     # never matches
```

The real value is `1-2.2:1.0` — bus/port **plus the interface suffix**. A rule that never
matches fails silently: no error, no log line anyone reads, just a symlink that never
appears. ttymap reads the value from sysfs, and rejects `2.2` at config-parse time:

```
$ ttymap plan
config error: alias 'ttyArm': kernels='2.2' is not a USB interface id
(expected something like '1-2.2:1.0')
```

### Trap 2 — cheap adapters have no serial number

A CH340 (`1a86:7523`) usually ships without an `iSerialNumber`. Two of them on the same
machine are indistinguishable by identity, so a rule matching `idVendor`/`idProduct` gives
both devices the same name — and the second one wins, non-deterministically.

If the device has a serial number, `ttymap init` binds by identity (the device can move
ports and still be found). If it doesn't, it binds by physical port and says why:

```toml
[aliases.ttyArm]
match   = "port"
kernels = "1-2.2:1.0"
# no USB serial number: bound to this physical port on purpose
```

## Commands

| Command | What it does |
|---|---|
| `scan [--json]` | List USB serial ports with identity, port, driver, symlinks, and holders |
| `init` | Print a config skeleton for the devices attached right now |
| `plan` | Resolve the config against current devices; print the rules. Changes nothing |
| `apply [--dry-run] [--force]` | Write rules, reload udev, verify. Backs up; refuses to clobber foreign files |
| `verify [--json]` | Re-check every alias. Exit code 1 on mismatch — safe to use in CI or systemd |
| `doctor` | Alias resolution, unpinned devices, busy ports, rules freshness |

Global flags: `-c/--config`, `--root` (read-only alternate filesystem root, for testing),
`--demo` (synthetic device tree — try the whole tool with no hardware attached).

## Config

```toml
[aliases.ttyLidar]          # identity-based: survives a different USB port
match  = "usb"
vid    = "0403"
pid    = "6001"
serial = "A10KZ9PQ"

[aliases.ttyArm]            # port-based: for devices with no serial number
match   = "port"
kernels = "1-2.2:1.0"
mode    = "0666"            # optional
group   = "dialout"         # optional
```

## Guarantees

- **Read-only by default.** `scan`, `plan`, `verify`, `doctor` never write. Ports held by
  another process are reported, not touched — a tty is a single queue, so anything you read
  the driver never sees.
- **`apply` backs up before writing**, and refuses to overwrite a rules file ttymap did not
  generate unless you pass `--force`.
- **No partial rules.** If any alias cannot be resolved, nothing is written.
- **Verification is part of `apply`**, not a separate step you might skip.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Ran fine, but something is wrong (unresolved alias, missing symlink, mismatched device) |
| 2 | Usage or config error |

## Limitations

- Linux only, and it needs `udevadm` (systemd). Not applicable to macOS or Windows.
- USB serial devices only. On-board UARTs and pseudo-terminals are ignored — they have no
  USB descriptor to identify them by, so `ttyS0` stays `ttyS0`.
- `KERNELS` is stable across reboots but **not** across physical re-plugging into a different
  port. That is the point of port-based matching; if you need the device to survive being
  moved, the device needs a serial number.
- Rules are written to `/etc/udev/rules.d/99-ttymap.rules`. Anything in
  `/etc/udev/rules.d/` with a higher number runs later and can override them.

## Development

```bash
python3 -m unittest discover -s tests -t . -v     # 41 tests, no hardware needed
PYTHONPATH=src python3 -m ttymap scan --demo      # full CLI against a synthetic tree
```

The test suite builds a fake `/sys` + `/dev` tree in a temp directory, so discovery, rule
generation, conflict detection and verification are all covered without a serial port.

## License

MIT.
