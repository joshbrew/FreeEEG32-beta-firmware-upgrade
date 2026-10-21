"""Flash FreeEEG32 directly with ST-Link and STM32CubeProgrammer (no Blue Pill)."""
import argparse
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import struct


def local_tool(name):
    """Find portable tools installed by Firmware/tools without changing global PATH."""
    suffix = '.exe' if os.name == 'nt' else ''
    for parent in [Path.cwd(), *list(Path(__file__).resolve().parents)[:4]]:
        folder = parent / '.tools'
        if folder.is_dir():
            matches = sorted(folder.rglob(name + suffix))
            if matches:
                return str(matches[0])
    return None


def find_gcc_dir():
    configured = os.environ.get('FREEEEG32_GCC_DIR')
    if configured:
        return configured
    path = shutil.which('arm-none-eabi-gcc') or local_tool('arm-none-eabi-gcc')
    if path:
        return str(Path(path).parent)
    if os.name == 'nt':
        for var in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
            folder = os.environ.get(var)
            if not folder:
                continue
            for pattern in ('GNU Arm Embedded Toolchain/*/bin/arm-none-eabi-gcc.exe',
                            'Arm GNU Toolchain arm-none-eabi/*/bin/arm-none-eabi-gcc.exe'):
                matches = sorted(Path(folder).glob(pattern))
                if matches:
                    return str(matches[-1].parent)
    return None


def image_address(image, explicit=None):
    if image.suffix.lower() != '.bin':
        if explicit:
            raise ValueError('--address is only for raw .bin images; HEX/ELF contain their own addresses')
        return None
    if not 8 <= image.stat().st_size <= 2 * 1024 * 1024:
        raise ValueError('Raw binary must fit the STM32H743ZI 2 MB flash')
    with image.open('rb') as stream:
        stream.seek(0x400)
        header = stream.read(20)
    # Our relocated application has a fixed board header. Do not overwrite its loader.
    relocated = len(header) == 20 and struct.unpack('<5I', header) == (0x42474546, 1, 0x32334546, 0x08020000, 0x080e0000)
    address = explicit or ('0x08020000' if relocated else '0x08000000')
    if address not in ('0x08000000', '0x08020000') or (relocated and address != '0x08020000'):
        raise ValueError('Image address does not match the supported firmware layout')
    if address == '0x08020000' and image.stat().st_size > 768 * 1024:
        raise ValueError('Relocated application exceeds its 768 KB flash region')
    return address


def programmer_path(explicit=None):
    if explicit:
        return explicit
    path = shutil.which('STM32_Programmer_CLI')
    if path:
        return path
    if os.name == 'nt':
        for var in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
            root = os.environ.get(var)
            if root:
                path = Path(root) / 'STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/STM32_Programmer_CLI.exe'
                if path.is_file():
                    return str(path)
    return None


def flash_command(image, programmer, serial=None, address=None, connect='under-reset'):
    image = Path(image).resolve()
    if not image.is_file() or image.suffix.lower() not in ('.hex', '.bin', '.elf'):
        raise ValueError('Choose an existing .hex, .bin or .elf firmware file')
    address = image_address(image, address)
    if connect not in ('under-reset', 'normal'): raise ValueError('Unsupported connection mode')
    command = [programmer, '-c', 'port=SWD',
               'mode=UR' if connect == 'under-reset' else 'mode=NORMAL',
               'reset=HWrst' if connect == 'under-reset' else 'reset=SWrst', 'freq=1000']
    if serial:
        command += ['sn=' + serial]
    command += ['-w', str(image)]
    if image.suffix.lower() == '.bin':
        command += [address]
    command += ['-v', '-rst']
    return command


def tcl_quote(value):
    value = str(value)
    if '\n' in value or '\r' in value:
        raise ValueError('Newlines are not allowed in OpenOCD arguments')
    for original, escaped in (('\\', '\\\\'), ('$', '\\$'), ('[', '\\['), (']', '\\]'), ('"', '\\"')):
        value = value.replace(original, escaped)
    return '"' + value + '"'


def openocd_command(image, executable, serial=None, address=None, probe='stlink', connect='under-reset'):
    image = Path(image).resolve()
    if not image.is_file() or image.suffix.lower() not in ('.hex', '.bin', '.elf'):
        raise ValueError('Choose an existing .hex, .bin or .elf firmware file')
    address = image_address(image, address)
    if probe not in ('stlink', 'cmsis-dap'):
        raise ValueError('Unsupported probe')
    if connect not in ('under-reset', 'normal'): raise ValueError('Unsupported connection mode')
    args = [executable]
    for scripts in (Path(executable).resolve().parent.parent / 'share/openocd/scripts',
                    Path(executable).resolve().parent.parent / 'scripts'):
        if (scripts / 'target/stm32h7x.cfg').is_file():
            args += ['-s', str(scripts)]
            break
    if probe == 'stlink':
        here = Path(__file__).resolve().parent
        candidates = [here / 'tools/openocd-stlink.cfg', here.parent / 'tools/openocd-stlink.cfg']
        config = next((p for p in candidates if p.is_file()), None)
        if not config:
            raise ValueError('Missing tools/openocd-stlink.cfg; keep the release tools folder beside flash.py')
        if connect == 'normal': args += ['-c', 'set FREEEEG32_CONNECT_NORMAL 1']
        args += ['-f', str(config)]
    else:
        args += ['-f', 'interface/cmsis-dap.cfg', '-c', 'transport select swd', '-f', 'target/stm32h7x.cfg',
                 '-c', 'adapter speed 1000', '-c',
                 'reset_config none; cortex_m reset_config sysresetreq' if connect == 'normal' else
                 'reset_config srst_only srst_nogate connect_assert_srst']
    if serial:
        args += ['-c', 'adapter serial ' + tcl_quote(serial)]
    args += ['-c',
             'program ' + tcl_quote(image.as_posix()) + ' verify reset exit' + (' ' + address if address else '')]
    return args


def default_image():
    here = Path(__file__).resolve().parent
    candidates = [here / 'freeeeg32-factory.hex', here.parent / 'build/uf2/freeeeg32-factory.hex',
                  here.parents[1] / 'Precompiled/freeeeg32-factory.hex',
                  here.parent / 'build/release/freeeeg32-beta.hex']
    return str(next((path for path in candidates if path.is_file()), candidates[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', nargs='?', default=default_image())
    parser.add_argument('--backend', choices=['auto', 'cube', 'openocd'], default='auto')
    parser.add_argument('--programmer', help='Path to STM32_Programmer_CLI')
    parser.add_argument('--openocd', help='Path to OpenOCD')
    parser.add_argument('--probe', choices=['stlink', 'cmsis-dap'], default='stlink', help='OpenOCD probe type')
    parser.add_argument('--address', help='Raw BIN load address: 0x08000000 or 0x08020000')
    parser.add_argument('--serial', help='Select ST-Link serial when several probes are connected')
    parser.add_argument('--connect', choices=['under-reset', 'normal'], default='under-reset',
                        help='Use normal/software-reset connection for a probe without working NRST')
    parser.add_argument('--dry-run', action='store_true', help='Show command without accessing the board')
    args = parser.parse_args()
    if args.backend == 'auto':
        args.backend = 'cube' if programmer_path(args.programmer) else 'openocd'
    try:
        if args.backend == 'cube':
            programmer = programmer_path(args.programmer)
            if not programmer and not args.dry_run:
                parser.error('Install STM32CubeProgrammer, pass --programmer PATH, or use --backend openocd')
            command = flash_command(args.image, programmer or 'STM32_Programmer_CLI', args.serial, args.address, args.connect)
        else:
            executable = args.openocd or local_tool('openocd') or shutil.which('openocd')
            if not executable and not args.dry_run:
                parser.error('Run Firmware/tools/setup-windows.ps1 or setup-linux.sh, or pass --openocd PATH')
            command = openocd_command(args.image, executable or 'openocd', args.serial, args.address, args.probe, args.connect)
    except ValueError as exc:
        parser.error(str(exc))
    print(subprocess.list2cmdline(command) if os.name == 'nt' else shlex.join(command))
    if not args.dry_run:
        subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
