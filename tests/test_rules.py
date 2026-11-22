import os
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ttymap import demo  # noqa: E402
from ttymap import rules as rules_mod  # noqa: E402
from ttymap.config import Alias, Config  # noqa: E402
from ttymap.sysfs import discover  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(os.path.dirname(HERE), "examples", "ttymap.toml")


def alias(name, **spec):
    spec.setdefault("match", "usb")
    return Alias(name, spec)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.root = demo.build()
        self.devices = discover(self.root)
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_example_config_binds_all_four(self):
        entries = rules_mod.plan(Config.load(EXAMPLE), self.devices)
        self.assertTrue(all(e.ok for e in entries))
        bound = {e.alias.name: e.device.name for e in entries}
        self.assertEqual(bound["ttyArm"], "ttyUSB0")
        self.assertEqual(bound["ttyLidar"], "ttyUSB2")

    def test_two_aliases_cannot_claim_one_device(self):
        cfg = Config([
            alias("a", vid="10c4", pid="ea60", serial="0001"),
            alias("b", vid="10c4", pid="ea60", serial="0001"),
        ])
        entries = rules_mod.plan(cfg, self.devices)
        self.assertTrue(entries[0].ok)
        self.assertIsNone(entries[1].device)
        self.assertIn("already claimed", entries[1].conflict)

    def test_ambiguous_usb_match_when_devices_share_identity(self):
        twin = ("ttyUSB3", "1a86", "7523", None, "wch.cn", "USB2.0-Serial", "1-2.5", "ch341-uart")
        original = demo.DEVICES
        demo.DEVICES = original + [twin]
        self.addCleanup(lambda: setattr(demo, "DEVICES", original))
        devices = discover(demo.build())
        entries = rules_mod.plan(Config([alias("ttyArm", vid="1a86", pid="7523")]), devices)
        self.assertIsNone(entries[0].device)
        self.assertIn("matches 2 devices", entries[0].conflict)

    def test_missing_device_is_reported_not_crashed(self):
        entries = rules_mod.plan(Config([alias("ttyGhost", vid="ffff", pid="ffff")]), self.devices)
        self.assertFalse(entries[0].ok)
        self.assertEqual(entries[0].status(), "no matching device")


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.root = demo.build()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_header_and_one_rule_per_alias(self):
        cfg = Config([alias("ttyA", vid="10c4", pid="ea60", serial="0001")])
        text = rules_mod.render(rules_mod.plan(cfg, discover(self.root)), cfg)
        self.assertIn(rules_mod.MARKER, text)
        self.assertEqual(text.count('SYMLINK+="'), 1)
        self.assertTrue(text.endswith("\n"))


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.root = demo.build()
        self.devices = discover(self.root)
        self.cfg = Config([alias("ttyA", vid="10c4", pid="ea60", serial="0001")])
        self.path = rules_mod.rules_path(self.root)
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_creates_file_and_backs_up_previous_one(self):
        entries = rules_mod.plan(self.cfg, self.devices)
        rules_mod.write_rules(entries, self.cfg, root=self.root)
        first = pathlib.Path(self.path).read_text(encoding="utf-8")
        path, backup = rules_mod.write_rules(entries, self.cfg, root=self.root)
        self.assertEqual(path, self.path)
        self.assertIsNotNone(backup)
        self.assertEqual(pathlib.Path(backup).read_text(encoding="utf-8"), first)

    def test_refuses_to_clobber_foreign_rules(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('SUBSYSTEM=="tty", SYMLINK+="mine"\n')
        entries = rules_mod.plan(self.cfg, self.devices)
        with self.assertRaises(RuntimeError):
            rules_mod.write_rules(entries, self.cfg, root=self.root)
        self.assertIn("mine", pathlib.Path(self.path).read_text(encoding="utf-8"))

    def test_force_overwrites(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('SUBSYSTEM=="tty", SYMLINK+="mine"\n')
        entries = rules_mod.plan(self.cfg, self.devices)
        rules_mod.write_rules(entries, self.cfg, root=self.root, force=True)
        self.assertIn(rules_mod.MARKER, pathlib.Path(self.path).read_text(encoding="utf-8"))


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.root = demo.build()
        self.devroot = os.path.join(self.root, "dev")
        self.devices = discover(self.root)
        self.cfg = Config([
            alias("ttyChassis", vid="10c4", pid="ea60", serial="0001"),
            alias("ttyLidar", vid="0403", pid="6001", serial="A10KZ9PQ"),
        ])
        self.addCleanup(shutil.rmtree, self.root, True)

    def _link(self, name, target):
        os.symlink(os.path.join(".", target), os.path.join(self.devroot, name))

    def test_missing_symlinks_fail(self):
        checks = rules_mod.verify(self.cfg, self.devices, devroot=self.devroot)
        self.assertFalse(any(c.ok for c in checks))

    def test_correct_symlinks_pass(self):
        self._link("ttyChassis", "ttyUSB1")
        self._link("ttyLidar", "ttyUSB2")
        checks = rules_mod.verify(self.cfg, self.devices, devroot=self.devroot)
        self.assertTrue(all(c.ok for c in checks))

    def test_swapped_symlinks_are_caught(self):
        # The failure mode that makes people distrust udev: rules exist, names
        # exist, and the lorry is steering the wrong wheel.
        self._link("ttyChassis", "ttyUSB2")
        self._link("ttyLidar", "ttyUSB1")
        checks = {c.alias: c for c in rules_mod.verify(self.cfg, self.devices, devroot=self.devroot)}
        self.assertFalse(checks["ttyChassis"].ok)
        self.assertIn("does not match", checks["ttyChassis"].message)

    def test_symlink_to_unknown_device_is_caught(self):
        self._link("ttyChassis", "ttyS0")
        checks = rules_mod.verify(self.cfg, self.devices, devroot=self.devroot)
        self.assertIn("not a known USB serial port", checks[0].message)


if __name__ == "__main__":
    unittest.main()
