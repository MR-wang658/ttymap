import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ttymap import config as config_mod  # noqa: E402
from ttymap.config import Alias, Config, ConfigError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(os.path.dirname(HERE), "examples", "ttymap.toml")


class AliasTest(unittest.TestCase):
    def test_usb_rule_contains_identity(self):
        alias = Alias("ttyLidar", {"match": "usb", "vid": "0403", "pid": "6001", "serial": "ABC"})
        self.assertEqual(
            alias.rule(),
            'SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", '
            'ATTRS{serial}=="ABC", SYMLINK+="ttyLidar"',
        )

    def test_port_rule_uses_kernels(self):
        alias = Alias("ttyArm", {"match": "port", "kernels": "1-2.2:1.0", "mode": "0666"})
        self.assertEqual(
            alias.rule(),
            'SUBSYSTEM=="tty", KERNELS=="1-2.2:1.0", MODE="0666", SYMLINK+="ttyArm"',
        )

    def test_by_path_fragment_is_rejected(self):
        # The exact mistake this tool exists to prevent.
        with self.assertRaises(ConfigError):
            Alias("ttyBad", {"match": "port", "kernels": "2.2"})

    def test_usb_match_requires_vid_and_pid(self):
        with self.assertRaises(ConfigError):
            Alias("ttyBad", {"match": "usb", "vid": "0403"})

    def test_alias_name_is_validated(self):
        with self.assertRaises(ConfigError):
            Alias("../evil", {"match": "port", "kernels": "1-2.2:1.0"})

    def test_serial_makes_match_more_specific(self):
        with_serial = Alias("a", {"match": "usb", "vid": "1", "pid": "2", "serial": "x"})
        without = Alias("b", {"match": "usb", "vid": "1", "pid": "2"})
        self.assertGreater(with_serial.specificity, without.specificity)


class ConfigTest(unittest.TestCase):
    def test_example_config_loads(self):
        cfg = Config.load(EXAMPLE)
        self.assertEqual([a.name for a in cfg.aliases], ["ttyArm", "ttyChassis", "ttyLidar", "ttyAux"])

    def test_missing_aliases_table(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write("[other]\nkey = 1\n")
            path = fh.name
        self.addCleanup(os.unlink, path)
        with self.assertRaises(ConfigError):
            Config.load(path)

    @unittest.skipIf(config_mod._toml is None, "interpreter has no TOML parser")
    def test_builtin_parser_agrees_with_tomllib(self):
        text = pathlib.Path(EXAMPLE).read_text(encoding="utf-8")
        self.assertEqual(config_mod._mini_parse(text), config_mod._toml.loads(text))

    def test_builtin_parser_handles_comments_and_quotes(self):
        parsed = config_mod._mini_parse(
            '# leading comment\n[aliases.x]\nmatch = "usb"  # trailing\nvid = "1a86"\n'
        )
        self.assertEqual(parsed, {"aliases": {"x": {"match": "usb", "vid": "1a86"}}})

    def test_builtin_parser_rejects_bad_line(self):
        with self.assertRaises(ConfigError):
            config_mod._mini_parse("[aliases.x]\nthis is not a pair\n")


if __name__ == "__main__":
    unittest.main()
