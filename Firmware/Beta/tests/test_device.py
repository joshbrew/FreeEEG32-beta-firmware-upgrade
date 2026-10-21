"""Exercise USB discovery, update and settings flows without opening a real device."""
import contextlib
import io
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BETA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BETA))
sys.path.insert(0, str(BETA.parent / 'UF2'))
import device
import board_tools
from pack import uf2_file

TAG = 'FreeEEG32-build:' + '0123456789abcdef' * 2
OTHER_TAG = 'FreeEEG32-build:' + 'fedcba9876543210' * 2


def firmware(tag=TAG):
    raw = bytearray(1536)
    struct.pack_into('<II', raw, 0, 0x20020000, 0x08020501)
    struct.pack_into('<5I', raw, 0x400, 0x42474546, 1, 0x32334546, 0x08020000, 0x080e0000)
    raw[0x440:0x440 + len(tag) + 1] = tag.encode() + b'\0'
    return uf2_file(raw)


class Clock:
    def __init__(self):
        self.value = 0

    def now(self):
        self.value += 0.001
        return self.value

    def sleep(self, duration):
        self.value += duration


class Connection:
    def __init__(self, hardware):
        self.hw = hardware
        self.buffer = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @property
    def in_waiting(self):
        return min(7, len(self.buffer))

    def reset_input_buffer(self):
        self.buffer.clear()

    def flush(self):
        pass

    def write(self, data):
        command = data.decode().strip().removeprefix('!')
        self.hw.commands.append(command)
        word = command.split()[0]
        if command == self.hw.fail_command:
            reply = 'ERR test command failed'
        elif word == 'INFO':
            tag = self.hw.running_tag if self.hw.phase == 2 else OTHER_TAG
            reply = f'OK INFO FreeEEG32-beta qos-4 update=UF2 build={tag}'
        elif word == 'BOOTLOADER':
            self.hw.phase = 1
            (self.hw.drive / 'INFO_UF2.TXT').write_text(f'Board-ID: {device.BOARD_ID}\n')
            reply = 'OK BOOTLOADER'
        elif word == 'SETTINGS':
            reply = f'OK SETTINGS rate={self.hw.rate} source=defaults dirty={self.hw.dirty} gains=' + ','.join(['8'] * 32)
        elif word == 'RATE':
            self.hw.rate = command.split()[1]
            self.hw.dirty = 1
            reply = 'OK ' + command
        elif word in ('GAIN', 'PRESET'):
            self.hw.dirty = 1
            reply = 'OK ' + command
        elif word in ('SAVE', 'LOAD', 'FACTORY'):
            self.hw.dirty = 0
            reply = 'OK ' + word
        else:
            reply = 'OK ' + word
        self.buffer.extend(reply.encode() + b'\r\n')

    def read(self, count):
        result = self.buffer[:count]
        del self.buffer[:count]
        return result


class Hardware:
    def __init__(self, drive):
        self.drive = Path(drive).resolve()
        self.drive.mkdir()
        self.phase = 0
        self.commands = []
        self.running_tag = TAG
        self.restart = True
        self.rate = '512'
        self.dirty = 0
        self.fail_command = None
        self.old = device.Port('COM5', 'board-A', '1-1')
        self.new = device.Port('COM9', 'board-A', '1-1')
        self.other = device.Port('COM8', 'board-B', '1-2')
        self.opened = []

    def ports(self):
        return ([self.old] if self.phase == 0 else [self.new] if self.phase == 2 else []) + [self.other]

    def is_drive(self, path):
        if self.phase == 1 and self.restart and (self.drive / 'firmware.uf2').exists():
            self.phase = 2
            (self.drive / 'INFO_UF2.TXT').unlink()
        return Path(path) == self.drive and (self.drive / 'INFO_UF2.TXT').exists()

    def drives(self):
        return [self.drive] if self.is_drive(self.drive) else []

    def open(self, port):
        self.opened.append(port)
        assert port.serial == 'board-A', 'Never open another board during verification'
        return Connection(self)

    @contextlib.contextmanager
    def installed(self):
        clock = Clock()
        with patch.object(device, 'serial_ports', self.ports), patch.object(device, 'uf2_drives', self.drives), \
             patch.object(device, 'is_uf2_drive', self.is_drive), patch.object(device, 'open_port', self.open), \
             patch.object(device.time, 'monotonic', clock.now), patch.object(device.time, 'sleep', clock.sleep), \
             patch.object(board_tools, 'report_folder', return_value=self.drive.parent / 'reports'):
            yield


class DeviceTests(unittest.TestCase):
    def test_detection_uses_board_identity_not_shared_st_vid_pid(self):
        def port(name, product, vid=0x0483, pid=0x5740):
            return types.SimpleNamespace(device=name, product=product, manufacturer='', description='',
                                         vid=vid, pid=pid, serial_number=name, location='1-1')
        enumeration = types.SimpleNamespace(comports=lambda: [port('A', 'FreeEEG32 EEG + Control'),
            port('B', 'STM32 Virtual ComPort'), port('C', 'FreeEEG32', pid=0x1234)])
        with patch.dict(sys.modules, {'serial': types.ModuleType('serial'),
             'serial.tools': types.SimpleNamespace(list_ports=enumeration)}), \
             patch.object(device, 'windows_usb_product', return_value=''):
            self.assertEqual([p.device for p in device.serial_ports()], ['A'])

    def test_generic_windows_com_name_uses_usb_bus_product(self):
        port = types.SimpleNamespace(device='COM5', product=None, manufacturer='Microsoft',
                                     description='USB Serial Device', vid=0x0483, pid=0x5740,
                                     serial_number='ABC123', location='1-2')
        enumeration = types.SimpleNamespace(comports=lambda: [port])
        with patch.dict(sys.modules, {'serial': types.ModuleType('serial'),
             'serial.tools': types.SimpleNamespace(list_ports=enumeration)}), \
             patch.object(device, 'windows_usb_product', return_value='FreeEEG32 EEG + Control') as lookup:
            self.assertEqual(device.serial_ports(), [device.Port('COM5', 'ABC123', '1-2')])
            lookup.assert_called_once_with('ABC123')

    def test_one_board_is_automatic_multiple_require_selection(self):
        a, b = device.Port('COM1', 'A'), device.Port('COM2', 'B')
        with patch.object(device, 'serial_ports', return_value=[a]), patch.object(device, 'uf2_drives', return_value=[]):
            self.assertEqual(device.select_target().port, a)
        self.assertEqual(device.choose([a, b], input_fn=lambda _: '2'), b)
        with patch.object(device.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(device.DeviceError, 'Select one board'):
                device.choose([a, b])

    def test_unrelated_drives_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'INFO_UF2.TXT').write_text('Board-ID: Another-board\n')
            with patch.object(device, 'mount_paths', return_value=[root]):
                self.assertEqual(device.uf2_drives(), [])
                (root / 'INFO_UF2.TXT').write_text(f'Board-ID: {device.BOARD_ID}\n')
                self.assertEqual(device.uf2_drives(), [root])

    def test_valid_shuffled_uf2_and_crc_checked(self):
        data = firmware()
        blocks = [data[i:i + 512] for i in range(0, len(data), 512)]
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'image.uf2'
            image.write_bytes(b''.join(reversed(blocks)))
            self.assertEqual(device.read_image(image).build, TAG)
            for offset in (0, 8, 12, 16, 20, 24, 28, 64, 288, 316, 508):
                corrupted = bytearray(data)
                corrupted[offset] ^= 1
                image.write_bytes(corrupted)
                with self.subTest(offset=offset), self.assertRaises(device.DeviceError):
                    device.read_image(image)
            image.write_bytes(blocks[0] * len(blocks))
            with self.assertRaisesRegex(device.DeviceError, 'duplicate'):
                device.read_image(image)

    def test_legacy_image_rejected_before_board_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'legacy.uf2'
            image.write_bytes(firmware('old-firmware'))
            with patch.object(device, 'select_target') as select:
                with self.assertRaisesRegex(device.DeviceError, 'no verifiable build ID'):
                    device.update(image)
                select.assert_not_called()

    def test_update_reconnects_by_uid_when_com_number_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hw = Hardware(root / 'drive')
            image = root / 'application.uf2'
            image.write_bytes(firmware())
            output = io.StringIO()
            with hw.installed(), contextlib.redirect_stdout(output):
                device.update(image, port='COM5')
            self.assertEqual(hw.commands, ['STOP', 'INFO', 'BOOTLOADER', 'STOP', 'INFO', 'START'])
            self.assertEqual(hw.opened, [hw.old, hw.new])
            self.assertEqual((hw.drive / 'firmware.uf2').read_bytes(), firmware())
            self.assertIn('Firmware verified', output.getvalue())

    def test_already_in_loader_needs_no_serial_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hw = Hardware(root / 'drive')
            hw.phase = 1
            (hw.drive / 'INFO_UF2.TXT').write_text(f'Board-ID: {device.BOARD_ID}\n')
            image = root / 'application.uf2'
            image.write_bytes(firmware())
            with hw.installed():
                device.update(image, drive=hw.drive)
            self.assertNotIn('BOOTLOADER', hw.commands)
            self.assertEqual(hw.opened, [hw.new])

    def test_wrong_running_build_never_reports_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hw = Hardware(root / 'drive')
            hw.running_tag = OTHER_TAG
            image = root / 'application.uf2'
            image.write_bytes(firmware())
            output = io.StringIO()
            with hw.installed(), contextlib.redirect_stdout(output):
                with self.assertRaisesRegex(device.DeviceError, 'different firmware build'):
                    device.update(image, port='COM5')
            self.assertNotIn('Firmware verified', output.getvalue())
            self.assertNotIn('START', hw.commands)

    def test_copy_disconnection_only_succeeds_if_running_build_matches(self):
        for restart in (True, False):
            with self.subTest(restart=restart), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                hw = Hardware(root / 'drive')
                hw.restart = restart
                image = root / 'application.uf2'
                image.write_bytes(firmware())
                with hw.installed(), patch.object(device.os, 'fsync', side_effect=OSError('USB disconnected')):
                    if restart:
                        device.update(image, port='COM5')
                    else:
                        with self.assertRaisesRegex(device.DeviceError, 'Copy failed.*restart was not verified'):
                            device.update(image, port='COM5')

    def test_reconnect_never_uses_another_existing_board(self):
        a, b = device.Port('COM1', 'A'), device.Port('COM2', 'B')
        with patch.object(device, 'serial_ports', return_value=[b]):
            self.assertEqual(device.reconnect_candidates(a, [a, b]), [])
            self.assertEqual(device.reconnect_candidates(None, [a, b]), [])

    def test_wait_for_new_drive_does_not_use_an_existing_loader(self):
        existing = Path('already-mounted')
        clock = Clock()
        with patch.object(device, 'uf2_drives', return_value=[existing]), \
             patch.object(device, 'is_uf2_drive', return_value=True), \
             patch.object(device.time, 'monotonic', clock.now), patch.object(device.time, 'sleep', clock.sleep):
            with self.assertRaisesRegex(device.DeviceError, 'did not mount'):
                device.wait_for_drive([existing], timeout=1)

    def test_verification_retries_while_serial_driver_is_not_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder) / 'drive')
            hw.phase = 2
            with hw.installed(), patch.object(device, 'open_port', side_effect=[
                    device.DeviceError('serial driver not ready'), Connection(hw)]):
                info = device.verify_restart(device.Image(b'', TAG), hw.drive, hw.old, [hw.old, hw.other], timeout=2)
            self.assertEqual(device.fields(info)['build'], TAG)
            self.assertEqual(hw.commands[-1], 'START')

    def test_verified_firmware_reports_adc_start_failure_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder) / 'drive')
            hw.phase = 2
            hw.fail_command = 'START'
            with hw.installed():
                with self.assertRaisesRegex(device.DeviceError, 'Firmware build verified, but acquisition could not start'):
                    device.verify_restart(device.Image(b'', TAG), hw.drive, hw.old, [hw.old, hw.other], timeout=2)

    def test_settings_require_explicit_save_and_start(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder) / 'drive')
            responses = iter(['1', '1024', '2', 'ALL', '4', '4', '8'])
            with hw.installed():
                device.configure('COM5', input_fn=lambda _: next(responses))
            gains = [s for s in hw.commands if s.startswith('GAIN ')]
            self.assertEqual(gains, [f'GAIN {ch} 4' for ch in range(1, 33)])
            self.assertIn('RATE 1024', hw.commands)
            self.assertEqual(hw.commands.count('SAVE'), 1)
            self.assertEqual(hw.commands[-1], 'START')

    def test_invalid_settings_and_cancel_do_not_write_or_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder) / 'drive')
            responses = iter(['1', '999', '2', '33', '6', 'no', '0'])
            with hw.installed():
                device.configure('COM5', input_fn=lambda _: next(responses))
            self.assertTrue(all(cmd in ('STOP', 'INFO', 'SETTINGS') for cmd in hw.commands))

    def test_adc_error_keeps_settings_menu_open_and_stream_paused(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder) / 'drive')
            hw.fail_command = 'RATE 2048'
            responses = iter(['1', '2048', '0'])
            output = io.StringIO()
            with hw.installed(), contextlib.redirect_stdout(output):
                device.configure('COM5', input_fn=lambda _: next(responses))
            self.assertIn('Streaming remains paused', output.getvalue())
            self.assertNotIn('START', hw.commands)
            self.assertNotIn('SAVE', hw.commands)

    def test_reply_matching_ignores_longer_command_names(self):
        hw = types.SimpleNamespace(commands=[], phase=0, fail_command=None)
        connection = Connection(hw)
        connection.buffer.extend(b'\xa0\x01OK INFORMATION wrong\r\n')
        self.assertTrue(device.transact(connection, 'INFO').startswith('OK INFO FreeEEG32-beta'))


if __name__ == '__main__':
    unittest.main()
