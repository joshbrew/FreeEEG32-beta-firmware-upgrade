"""Build loader, relocated application, UF2 update and one-time SWD factory image."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from pack import APP_BASE, APP_META, STAGE_META, application_image, intel_hex, uf2_file
from precompiled import sync_bundle

HERE = Path(__file__).resolve().parent
BETA = HERE.parent / 'Beta'
sys.path.insert(0, str(BETA))
spec = importlib.util.spec_from_file_location('beta_build', BETA / 'build.py')
beta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(beta)


def function(source, signature):
    start = source.index(signature + '\n{')
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def build(gcc_dir=None, jobs=None, cpu_mhz=80):
    gcc_dir = gcc_dir or beta.find_gcc_dir()
    app = beta.build(gcc_dir, jobs, uf2=True, cpu_mhz=cpu_mhz)
    root = HERE.parent / 'build/source'
    out = HERE.parent / 'build/uf2'
    generated = out / 'boot-source'
    generated.mkdir(parents=True, exist_ok=True)
    objects = out / 'boot-objects'
    objects.mkdir(exist_ok=True)
    suffix = '.exe' if os.name == 'nt' else ''
    def tool(name):
        return str(Path(gcc_dir) / ('arm-none-eabi-' + name + suffix)) if gcc_dir else shutil.which('arm-none-eabi-' + name)
    gcc = tool('gcc')
    main = (root / 'Src/main.c').read_text(encoding='utf-8')
    # Keep the original ST notice with the reused generated clock configuration.
    notice = main[:main.index('/* Includes')]
    (generated / 'clock.c').write_text(notice + '\n#include "main.h"\n#include "clock_profile.h"\n' + function(main, 'void SystemClock_Config(void)') + '\n')
    system = (root / 'Src/system_stm32h7xx.c').read_text(encoding='utf-8')
    (generated / 'system_boot.c').write_text(system.replace('#define VECT_TAB_OFFSET  0x00020000UL', '#define VECT_TAB_OFFSET  0x00000000UL'))
    desc = (root / 'Src/usbd_desc.c').read_text(encoding='utf-8')
    desc = desc.replace('USBD_PID_HS     22336', 'USBD_PID_HS     22304')
    desc = desc.replace('"FreeEEG32 EEG + Control"', '"FreeEEG32 UF2 Bootloader"')
    desc = desc.replace('0x02,                       /*bDeviceClass*/', '0x00,                       /*bDeviceClass*/')
    desc = desc.replace('0x02,                       /*bDeviceSubClass*/', '0x00,                       /*bDeviceSubClass*/')
    (generated / 'boot_desc.c').write_text(desc)
    linker = (root / 'STM32H743ZITx_FLASH.ld').read_text(encoding='utf-8')
    linker = linker.replace('ORIGIN = 0x8020000, LENGTH = 768K', 'ORIGIN = 0x8000000, LENGTH = 128K')
    linker = linker.replace('  .board_id ORIGIN(FLASH) + 0x400 : { KEEP(*(.board_id)) } >FLASH\n', '')
    (generated / 'boot.ld').write_text(linker)
    # Pinned ST MSC driver with explicit cache-flush acknowledgement (storage writes are synchronous).
    scsi = (HERE / 'vendor/Class/MSC/Src/usbd_msc_scsi.c').read_text()
    scsi = scsi.replace('  case SCSI_TEST_UNIT_READY:', '''  case 0x35: /* SYNCHRONIZE CACHE(10): no deferred disk writes. */
    if (hmsc->cbw.dDataLength) { ret = -1; }
    else { hmsc->bot_data_length = 0; ret = 0; }
    break;
  case SCSI_TEST_UNIT_READY:''')
    (generated / 'boot_scsi.c').write_text(scsi)
    make = (root / 'Makefile').read_text()
    base_sources = re.search(r'C_SOURCES =\s*(.*?)# ASM sources', make, re.S).group(1).replace('\\', '').split()
    sources = [root / s for s in base_sources if s.startswith('Drivers/') or '/Core/Src/' in s]
    sources += [root / 'Src/usbd_conf.c', root / 'startup_stm32h743xx.s', BETA / 'Src/sysmem.c']
    sources += [p for p in (HERE / 'Src').glob('*.c') if p.name != 'board_id.c']
    sources += [HERE / 'Src/flash_probe.s']
    sources += list(generated.glob('*.c'))
    sources += [p for p in (HERE / 'vendor/Class/MSC/Src').glob('*.c')
                if p.name not in ('usbd_msc_scsi.c', 'usbd_msc_storage_template.c')]
    includes = [root / 'Inc', root / 'Drivers/STM32H7xx_HAL_Driver/Inc',
                root / 'Drivers/STM32H7xx_HAL_Driver/Inc/Legacy',
                root / 'Drivers/CMSIS/Device/ST/STM32H7xx/Include', root / 'Drivers/CMSIS/Include',
                root / 'Middlewares/ST/STM32_USB_Device_Library/Core/Inc',
                HERE / 'Inc', HERE / 'vendor/Class/MSC/Inc']
    cpu = ['-mcpu=cortex-m7', '-mthumb', '-mfpu=fpv5-d16', '-mfloat-abi=hard']
    # Recovery always uses the original 80 MHz profile, independently of the application.
    flags = cpu + ['-DUSE_HAL_DRIVER', '-DSTM32H743xx', '-DFREEEEG32_CPU_MHZ=80', '-Os', '-g', '-Wall', '-Wextra',
                   '-std=gnu11', '-ffunction-sections', '-fdata-sections'] + ['-I' + str(p) for p in includes]
    def run(args):
        result = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(result.stdout)
        return result.stdout
    def compile_one(source):
        obj = objects / (source.stem + '.o')
        output = run([gcc, *flags, '-c', str(source), '-o', str(obj)])
        return obj, output
    with ThreadPoolExecutor(max_workers=jobs or min(os.cpu_count() or 1, 8)) as pool:
        results = list(pool.map(compile_one, sources))
    (out / 'boot-warnings.log').write_text(''.join(output for _, output in results))
    elf = out / 'freeeeg32-bootloader.elf'
    run([gcc, *cpu, *[str(obj) for obj, _ in results], '-specs=nano.specs', '-T' + str(generated / 'boot.ld'),
         '-Wl,--gc-sections,-Map=' + str(out / 'freeeeg32-bootloader.map'), '-lc', '-lm', '-lnosys', '-o', str(elf)])
    run([tool('objcopy'), '-O', 'binary', str(elf), str(elf.with_suffix('.bin'))])
    print(run([tool('size'), str(elf)]))
    boot = elf.with_suffix('.bin').read_bytes()
    if not 8 < len(boot) <= 128 * 1024:
        raise RuntimeError('Bootloader exceeds its reserved sector')
    raw = (app / 'freeeeg32-beta.bin').read_bytes()
    image, record = application_image(raw)
    (out / 'freeeeg32-application.uf2').write_bytes(uf2_file(raw))
    (out / 'freeeeg32-application.hex').write_text(intel_hex([(APP_BASE, image), (APP_META, record), (STAGE_META, bytes(32))]))
    (out / 'freeeeg32-bootloader.hex').write_text(intel_hex([(0x08000000, boot)]))
    # Invalidate any previous pending stage on one-time factory installation/reinstallation.
    (out / 'freeeeg32-factory.hex').write_text(intel_hex([(0x08000000, boot), (APP_BASE, image),
                                                       (APP_META, record), (STAGE_META, bytes(32))]))
    files = ['freeeeg32-factory.hex', 'freeeeg32-application.uf2', 'freeeeg32-application.hex', 'freeeeg32-bootloader.hex']
    manifest = {'board': 'FreeEEG32-beta STM32H743ZI', 'version': 'qos-5-uf2-v1', 'hardware_validated': False,
                'build_id': json.loads((app / 'manifest.json').read_text())['build_id'],
                'compiler': json.loads((app / 'manifest.json').read_text())['compiler'],
                'settings_address': '0x081c0000', 'idle_mode': 'Sleep (WFI), clocks retained',
                'application_clocks': beta.clock_manifest(cpu_mhz), 'bootloader_cpu_mhz': 80,
                'application_address': hex(APP_BASE), 'maximum_application_bytes': 768 * 1024,
                'files': {name: {'bytes': (out / name).stat().st_size,
                                 'sha256': hashlib.sha256((out / name).read_bytes()).hexdigest()} for name in files}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with zipfile.ZipFile(out / 'freeeeg32-uf2-release.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files + ['manifest.json']:
            archive.write(out / name, name)
        for name in ('flash.py', 'flash.cmd', 'control.py', 'device.py', 'board_tools.py'):
            archive.write(BETA / name, name)
        for name in ('FreeEEG32.cmd', 'FreeEEG32.sh'):
            archive.write(HERE.parents[1] / name, name)
        if (HERE / 'README.md').exists():
            readme = (HERE / 'README.md').read_text(encoding='utf-8')
            readme = readme.replace('../../README.md#swd-wiring-what-a2--a4--a6-actually-mean', '#wiring-and-entry')
            readme = readme.replace('../../README.md#swd-programming', '#wiring-and-entry')
            readme = readme.replace('../../SetupGuides/images/st-link-v2-reference.jpg', 'st-link-v2-reference.jpg')
            readme = readme.replace('../Beta/README.md', 'CONTROL.md')
            readme = readme.replace('../../Flash/', 'Flash/')
            readme = readme.replace('../../SetupGuides/FreeEEG32_Stacking.md', 'STACKING.md')
            readme += '\n![SWD header reference](basic_layout_swd.png)\n'
            archive.writestr('README.md', readme)
        archive.write(HERE.parents[1] / 'SetupGuides/images/basic_layout_swd.png', 'basic_layout_swd.png')
        archive.write(HERE.parents[1] / 'SetupGuides/images/st-link-v2-reference.jpg', 'st-link-v2-reference.jpg')
        controls = (BETA / 'README.md').read_text(encoding='utf-8').replace('../UF2/README.md', 'README.md')
        controls = controls.replace('../../Flash/', 'Flash/')
        controls = controls.replace('../../SetupGuides/FreeEEG32_Stacking.md', 'STACKING.md')
        controls = controls.replace('../../SetupGuides/FreeEEG32_Programming_and_Updates.md', 'README.md#wiring-and-entry')
        archive.writestr('CONTROL.md', controls)
        stacking = (HERE.parents[1] / 'SetupGuides/FreeEEG32_Stacking.md').read_text(encoding='utf-8')
        stacking = stacking.replace('../AssemblyFiles/', 'https://github.com/joshbrew/FreeEEG32-beta-firmware-upgrade/blob/master/AssemblyFiles/')
        archive.writestr('STACKING.md', stacking)
        # Include the same clearly named platform launchers in precompiled bundles.
        for source in (HERE.parents[1] / 'Flash').rglob('*'):
            if not source.is_file() or source.suffix not in ('.md', '.cmd', '.sh'):
                continue
            relative = source.relative_to(HERE.parents[1]).as_posix()
            if source.suffix == '.md':
                guide = source.read_text(encoding='utf-8')
                guide = guide.replace('Firmware/UF2/README.md', 'README.md')
                guide = guide.replace('Firmware/Beta/README.md', 'CONTROL.md')
                guide = guide.replace('#swd-wiring-what-a2--a4--a6-actually-mean', '#wiring-and-entry')
                guide = guide.replace('#swd-programming', '#wiring-and-entry')
                archive.writestr(relative, guide)
            else:
                archive.write(source, relative)
        tooling = HERE.parent / 'tools'
        if tooling.exists():
            for source in tooling.iterdir():
                if source.is_file(): archive.write(source, 'tools/' + source.name)
    print(f'UF2 release bundle: {out / "freeeeg32-uf2-release.zip"}')
    beta.archive_build(out, ['freeeeg32-uf2-release.zip', 'manifest.json'], cpu_mhz, manifest['build_id'], 'uf2')
    if cpu_mhz == 80:
        sync_bundle(out / 'freeeeg32-uf2-release.zip', HERE.parents[1] / 'Precompiled')
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gcc-dir')
    parser.add_argument('--jobs', type=int)
    parser.add_argument('--cpu-mhz', type=int, choices=beta.CPU_PROFILES, default=80,
                        help='Application CPU clock (default: 80); bootloader stays at 80 MHz')
    args = parser.parse_args()
    build(args.gcc_dir, args.jobs, cpu_mhz=args.cpu_mhz)
