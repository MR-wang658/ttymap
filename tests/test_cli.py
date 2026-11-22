import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ttymap import cli  # noqa: E402
from ttymap.config import Config  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(os.path.dirname(HERE), "examples", "ttymap.toml")


def run(argv):
    """Run the CLI with its output captured. Returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class ScanTest(unittest.TestCase):
    def test_scan_demo_succeeds(self):
        code, out, _ = run(["scan", "--demo"])
        self.assertEqual(code, cli.OK)
        self.assertIn("ttyUSB0", out)

    def test_scan_reports_missing_serial_numbers(self):
        _, out, _ = run(["scan", "--demo"])
        self.assertIn("no USB serial number", out)

    def test_scan_json_is_parseable(self):
        code, out, _ = run(["scan", "--demo", "--json"])
        self.assertEqual(code, cli.OK)
        payload = json.loads(out)
        self.assertEqual(len(payload), 4)
        self.assertEqual(payload[0]["vid_pid"], "2341:0043")


class PlanAndApplyTest(unittest.TestCase):
    def test_plan_demo_succeeds(self):
        code, out, _ = run(["plan", "--demo", "-c", EXAMPLE])
        self.assertEqual(code, cli.OK)
        self.assertIn('SYMLINK+="ttyArm"', out)

    def test_apply_dry_run_prints_without_writing(self):
        code, out, _ = run(["apply", "--demo", "-c", EXAMPLE, "--dry-run"])
        self.assertEqual(code, cli.OK)
        self.assertIn("would write", out)

    def test_apply_on_fake_root_requires_dry_run(self):
        code, _, err = run(["apply", "--demo", "-c", EXAMPLE])
        self.assertEqual(code, cli.USAGE)
        self.assertIn("dry-run", err)

    def test_apply_refuses_unresolved_aliases(self):
        code, _, err = run(["apply", "--demo", "-c", "/dev/null", "--dry-run"])
        self.assertEqual(code, cli.USAGE)
        self.assertIn("config error", err)


class VerifyAndDoctorTest(unittest.TestCase):
    def test_verify_fails_when_aliases_do_not_resolve(self):
        self.assertEqual(run(["verify", "--demo", "-c", EXAMPLE])[0], cli.FAIL)

    def test_verify_json_shape(self):
        code, out, _ = run(["verify", "--demo", "-c", EXAMPLE, "--json"])
        self.assertEqual(code, cli.FAIL)
        payload = json.loads(out)
        self.assertEqual({entry["alias"] for entry in payload}, {"ttyArm", "ttyChassis", "ttyLidar", "ttyAux"})

    def test_doctor_reports_problems(self):
        code, out, _ = run(["doctor", "--demo", "-c", EXAMPLE])
        self.assertEqual(code, cli.FAIL)
        self.assertIn("problem(s) found", out)


class ConfigErrorsTest(unittest.TestCase):
    def test_missing_config_is_a_usage_error(self):
        code, _, err = run(["plan", "--demo", "-c", "/nonexistent.toml"])
        self.assertEqual(code, cli.USAGE)
        self.assertIn("cannot read", err)


class InitTest(unittest.TestCase):
    def test_init_output_can_be_loaded_back(self):
        code, out, _ = run(["init", "--demo"])
        self.assertEqual(code, cli.OK)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(out)
            path = fh.name
        self.addCleanup(os.unlink, path)
        cfg = Config.load(path)
        self.assertEqual(len(cfg.aliases), 4)
        self.assertTrue(any(a.match == "port" for a in cfg.aliases))


if __name__ == "__main__":
    unittest.main()
