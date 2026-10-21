"""Run the shared launchers with stub setup/device helpers, in both package layouts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASH = os.environ.get('FREEEEG32_TEST_BASH') or shutil.which('bash')


class USBLaunch(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell required')
    def test_windows_usb_update_finds_precompiled_uf2_on_fresh_clone(self):
        with tempfile.TemporaryDirectory(prefix='FreeEEG32 precompiled ') as folder:
            root, tooling, env = self.prepare(folder, True)
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / '.venv')],
                           check=True, capture_output=True, timeout=30)
            image = root / 'Precompiled/freeeeg32-application.uf2'
            image.parent.mkdir()
            image.write_bytes(b'test image; recording stub never flashes')
            shell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            args = [shell, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(tooling / 'launch.ps1'), '-Action', 'usb-update']
            result = subprocess.run(args, env=env, cwd=root.parent, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = json.loads((root / 'arguments.json').read_text())
            self.assertEqual(actual[:2], ['update', '--image'])
            self.assertEqual(Path(actual[2]).resolve(), image.resolve())

    @unittest.skipUnless(BASH and (os.name == 'posix' or os.environ.get('FREEEEG32_TEST_BASH')), 'Bash required')
    def test_linux_usb_update_finds_precompiled_uf2_on_fresh_clone(self):
        with tempfile.TemporaryDirectory(prefix='FreeEEG32 precompiled ') as folder:
            root, tooling, env = self.prepare(folder, True)
            image = root / 'Precompiled/freeeeg32-application.uf2'
            image.parent.mkdir()
            image.write_bytes(b'test image; recording stub never flashes')
            python = root / '.venv/bin/python'
            python.parent.mkdir(parents=True)
            python.write_text(f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n', newline='\n')
            python.chmod(0o755)
            result = subprocess.run([BASH, str(tooling / 'launch.sh'), 'usb-update'],
                                    env=env, cwd=root.parent, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            actual = json.loads((root / 'arguments.json').read_text())
            self.assertEqual(actual[:2], ['update', '--image'])
            self.assertEqual(Path(actual[2]).resolve(), image.resolve())

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell required')
    def test_setup_falls_back_when_py_launcher_cannot_find_python(self):
        with tempfile.TemporaryDirectory(prefix='FreeEEG32 Python fallback ') as folder:
            root = Path(folder)
            tools = root / 'tools'
            tools.mkdir()
            shutil.copy2(ROOT / 'Firmware/tools/setup-windows.ps1', tools)
            executables = root / 'bin'
            executables.mkdir()
            (executables / 'py.cmd').write_bytes(b'@echo No installed Python found! 1>&2\r\n@exit /b 101\r\n')
            (executables / 'python.cmd').write_bytes(f'@"{sys.executable}" %*\r\n'.encode())
            env = dict(os.environ, PATH=str(executables) + os.pathsep + os.environ['PATH'])
            shell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                     str(tools / 'setup-windows.ps1'), '-SerialOnly', '-NoSerialTools'],
                                    env=env, cwd=root, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('[READY] Python:', result.stdout)
            self.assertNotIn('[DOWNLOAD', result.stdout)
            detected = (root / '.tools/python-path.txt').read_text(encoding='utf-8-sig').strip()
            self.assertEqual(Path(detected), Path(sys.executable))

    def prepare(self, folder, repo):
        root = Path(folder)
        helpers = root / 'Firmware/Beta' if repo else root
        tooling = root / 'Firmware/tools' if repo else root / 'tools'
        helpers.mkdir(parents=True, exist_ok=True)
        tooling.mkdir(parents=True, exist_ok=True)
        for name in ('launch.ps1', 'launch.sh'):
            (tooling / name).write_bytes((ROOT / 'Firmware/tools' / name).read_bytes().replace(b'\r\n', b'\n'))
        (helpers / 'device.py').write_text(
            'import json,os,pathlib,sys\n'
            'pathlib.Path(os.environ["FREEEEG32_TEST_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
            'raise SystemExit(int(os.environ.get("FREEEEG32_TEST_EXIT", "0")))\n')
        (root / '.tools').mkdir()
        (root / '.tools/python-path.txt').write_text(sys.executable)
        # Setup stubs record the requested mode and never download/install anything.
        (tooling / 'setup-windows.ps1').write_text(
            'param([switch]$SerialOnly)\n'
            'if (!$SerialOnly) { throw "USB actions must request serial-only setup" }\n'
            'Set-Content -LiteralPath $env:FREEEEG32_TEST_SETUP -Value serial-only\n')
        (tooling / 'setup-linux.sh').write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            '[[ "$1" == --serial-only ]]\n'
            'printf serial-only > "$FREEEEG32_TEST_SETUP"\n', newline='\n')
        env = dict(os.environ, FREEEEG32_TEST_LOG=str(root / 'arguments.json'),
                   FREEEEG32_TEST_SETUP=str(root / 'setup.txt'))
        return root, tooling, env

    @unittest.skipUnless(os.name == 'nt', 'PowerShell required')
    def test_windows_repo_and_release_use_shared_device_helper(self):
        for repo in (True, False):
            with self.subTest(repo=repo), tempfile.TemporaryDirectory(prefix='FreeEEG32 shared ') as folder:
                root, tooling, env = self.prepare(folder, repo)
                subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(root / '.venv')],
                               check=True, capture_output=True, timeout=30)
                shell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
                for action in ('configure', 'usb-update', 'check', 'record', 'report', 'backup', 'restore'):
                    args = [shell, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                            str(tooling / 'launch.ps1'), '-Action', action, '-Port', 'COM5']
                    expected = [action, '--port', 'COM5']
                    if action == 'record': expected += ['--seconds', '10']
                    if action == 'restore':
                        settings_file = str(root / 'settings $[name] & spaces.json')
                        args += ['-SettingsFile', settings_file, '-Yes', '-Save', '-Advanced']
                        expected += ['--file', settings_file, '--advanced', '--yes', '--save']
                    if action == 'usb-update':
                        image = str(root / 'image $[name] & spaces.uf2')
                        args += ['-Image', image]
                        expected = ['update', '--image', image, '--port', 'COM5']
                    result = subprocess.run(args, env=env, cwd=root.parent, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(json.loads((root / 'arguments.json').read_text()), expected)
                    self.assertEqual((root / 'setup.txt').read_text().strip(), 'serial-only')
                env['FREEEEG32_TEST_EXIT'] = '17'
                result = subprocess.run(args, env=env, cwd=root.parent, capture_output=True, text=True, timeout=20)
                self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(BASH and (os.name == 'posix' or os.environ.get('FREEEEG32_TEST_BASH')), 'Bash required')
    def test_linux_repo_and_release_use_shared_device_helper(self):
        for repo in (True, False):
            with self.subTest(repo=repo), tempfile.TemporaryDirectory(prefix='FreeEEG32 shared ') as folder:
                root, tooling, env = self.prepare(folder, repo)
                python = root / '.venv/bin/python'
                python.parent.mkdir(parents=True)
                python.write_text(f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n', newline='\n')
                python.chmod(0o755)
                for action in ('configure', 'usb-update', 'check', 'record', 'report', 'backup', 'restore'):
                    arguments = ['--port', 'COM5' if os.name == 'nt' else '/dev/ttyACM0']
                    if action == 'restore':
                        arguments += ['--file', str(root / 'settings $[name] & spaces.json'), '--yes', '--save', '--advanced']
                    expected = [action, *arguments]
                    if action == 'usb-update':
                        image = str(root / 'image $[name] & spaces.uf2')
                        arguments += ['--image', image]
                        default = root / 'Firmware/build/uf2/freeeeg32-application.uf2' if repo else root / 'freeeeg32-application.uf2'
                        expected = ['update', '--image', default.as_posix(), *arguments]
                    result = subprocess.run([BASH, str(tooling / 'launch.sh'), action, *arguments],
                                            env=env, cwd=root.parent, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads((root / 'arguments.json').read_text())
                    # Git Bash can pass /c/... paths through to native Python on Windows.
                    if os.name == 'nt' and action == 'usb-update':
                        expected[2] = str(default).replace('\\', '/')
                        actual[2] = actual[2].replace('\\', '/')
                    self.assertEqual(actual, expected)
                    self.assertEqual((root / 'setup.txt').read_text().strip(), 'serial-only')
                env['FREEEEG32_TEST_EXIT'] = '17'
                result = subprocess.run([BASH, str(tooling / 'launch.sh'), action, *arguments],
                                        env=env, cwd=root.parent, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 17)


if __name__ == '__main__':
    unittest.main()
