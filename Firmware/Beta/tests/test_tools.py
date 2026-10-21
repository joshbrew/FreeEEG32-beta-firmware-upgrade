from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import flash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flash import flash_command, openocd_command, tcl_quote
from control import transact
from prepare import prepare


class FakePort:
    def __init__(self, reply):
        self.reply = bytearray(reply)
        self.written = bytearray()

    @property
    def in_waiting(self):
        return min(3, len(self.reply))

    def write(self, data):
        self.written.extend(data)

    def flush(self):
        pass

    def read(self, length):
        data = self.reply[:length]
        del self.reply[:length]
        return data


class ToolTests(unittest.TestCase):
    def test_fresh_clone_uses_tracked_factory_hex_and_local_build_takes_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            helper = root / 'Firmware/Beta/flash.py'
            helper.parent.mkdir(parents=True)
            tracked = root / 'Precompiled/freeeeg32-factory.hex'
            tracked.parent.mkdir()
            tracked.write_text(':00000001FF')
            with patch.object(flash, '__file__', str(helper)):
                self.assertEqual(Path(flash.default_image()), tracked)
                local = root / 'Firmware/build/uf2/freeeeg32-factory.hex'
                local.parent.mkdir(parents=True)
                local.write_text(':00000001FF')
                self.assertEqual(Path(flash.default_image()), local)

    def test_flash_verifies_and_resets_binary_at_base(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'firmware with spaces.bin'
            path.write_bytes(b'firmware')
            args = flash_command(path, 'programmer', '12345')
            self.assertIn('mode=UR', args)
            self.assertIn('sn=12345', args)
            self.assertEqual(args[-4:], [str(path.resolve()), '0x08000000', '-v', '-rst'])

    def test_hex_uses_embedded_address(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.hex'
            path.write_text(':00000001FF')
            args = flash_command(path, 'programmer')
            self.assertNotIn('0x08000000', args)
            self.assertEqual(args[-2:], ['-v', '-rst'])

    def test_normal_connection_does_not_require_probe_reset_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'app.hex'
            path.write_text(':00000001FF')
            args = flash_command(path, 'programmer', connect='normal')
            self.assertIn('mode=NORMAL', args)
            self.assertIn('reset=SWrst', args)
            self.assertNotIn('mode=UR', args)
            args = openocd_command(path, 'openocd', connect='normal')
            self.assertIn('set FREEEEG32_CONNECT_NORMAL 1', args)
            self.assertLess(args.index('set FREEEEG32_CONNECT_NORMAL 1'), args.index('-f'))

    def test_bad_image_rejected(self):
        with self.assertRaises(ValueError):
            flash_command('missing.bin', 'programmer')

    def test_openocd_uses_direct_stlink_config_and_escaped_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'image $[name].hex'
            path.write_text(':00000001FF')
            args = openocd_command(path, 'openocd', 'probe $[1]')
            self.assertTrue(any('openocd-stlink.cfg' in item for item in args))
            self.assertIn('\\$\\[name\\]', args[-1])
            self.assertIn('verify reset exit', args[-1])
            self.assertTrue(any('adapter serial "probe \\$\\[1\\]"' == item for item in args))
        with self.assertRaises(ValueError): tcl_quote('bad\npath')

    def test_relocated_binary_does_not_overwrite_loader(self):
        import struct
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'app.bin'
            image = bytearray(1536)
            struct.pack_into('<5I', image, 0x400, 0x42474546, 1, 0x32334546, 0x08020000, 0x080e0000)
            path.write_bytes(image)
            self.assertIn('0x08020000', flash_command(path, 'programmer'))
            with self.assertRaises(ValueError): flash_command(path, 'programmer', address='0x08000000')

    def test_fragmented_stop_after_binary(self):
        port = FakePort(b'\xa0\x02\xff\xc0OK STOP\r\n')
        self.assertEqual(transact(port, 'STOP'), 'OK STOP')
        self.assertEqual(port.written, b'!STOP\n')

    def test_device_error_and_timeout(self):
        with self.assertRaisesRegex(RuntimeError, 'ERR command'):
            transact(FakePort(b'ERR command\r\n'), 'BAD')
        with self.assertRaises(TimeoutError):
            transact(FakePort(b''), 'INFO', timeout=0.001)

    def test_preparation_is_repeatable_and_hooks_real_source(self):
        first = prepare()
        snapshot = (first / 'Src/main.c').read_bytes()
        prepare()
        self.assertEqual(snapshot, (first / 'Src/main.c').read_bytes())
        self.assertIn(b'FreeEEG32_Run();', snapshot)
        self.assertNotIn(b', SAI_DATASIZE_32);', snapshot)
        adc = (first / 'Src/ad7779.c').read_text()
        self.assertIn('ad7779_dev *dev = NULL;', adc)
        self.assertIn('*dec_val = dev->dec_rate_dec;', adc)
        usb = (first / 'Src/usbd_cdc_if.c').read_text()
        self.assertIn('memcpy(UserTxBufferHS, Buf, Len)', usb)
        self.assertIn('hcdc == NULL', usb)
        self.assertIn('FreeEEG32_Receive(Buf, *Len)', usb)


if __name__ == '__main__':
    unittest.main()
