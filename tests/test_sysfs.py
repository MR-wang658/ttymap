import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ttymap import demo  # noqa: E402
from ttymap.sysfs import discover  # noqa: E402


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self.root = demo.build()
        self.devices = {d.name: d for d in discover(self.root)}
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, True))

    def test_finds_every_port(self):
        self.assertEqual(sorted(self.devices), ["ttyACM0", "ttyUSB0", "ttyUSB1", "ttyUSB2"])

    def test_usb_identity(self):
        dev = self.devices["ttyUSB2"]
        self.assertEqual(dev.identity, "0403:6001")
        self.assertEqual(dev.serial, "A10KZ9PQ")
        self.assertEqual(dev.product, "FT232R USB UART")
        self.assertEqual(dev.driver, "ftdi_sio")

    def test_kernels_is_the_interface_not_the_by_path_fragment(self):
        # /dev/serial/by-path says "...usb-0:2.2:1.0-port0"; udev wants "1-2.2:1.0".
        dev = self.devices["ttyUSB0"]
        self.assertEqual(dev.kernels, "1-2.2:1.0")
        self.assertEqual(dev.usb_path, "1-2.2")

    def test_device_without_serial_is_reported(self):
        self.assertFalse(self.devices["ttyUSB0"].has_serial)
        self.assertTrue(self.devices["ttyUSB1"].has_serial)

    def test_symlinks_found_by_basename(self):
        links = self.devices["ttyUSB1"].symlinks
        self.assertTrue(any("by-id" in link for link in links))
        self.assertTrue(any("by-path" in link for link in links))

    def test_empty_root_is_not_an_error(self):
        self.assertEqual(discover("/nonexistent-root-for-ttymap-tests"), [])


if __name__ == "__main__":
    unittest.main()
