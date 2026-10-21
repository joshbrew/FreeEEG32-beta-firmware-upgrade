# FreeEEG32 UF2 loader and build tools

The custom loader uses the board's existing **PB14/PB15 USB data port**. Install
`freeeeg32-factory.hex` once with ST-Link, then use `!BOOTLOADER` or double-reset
to expose the **FREEEEG32** drive. Copy `freeeeg32-application.uf2` onto it. The
loader verifies the upload, resets, installs it and starts the EEG application.

`freeeeg32-factory.hex` is this fork's combined EEG application and UF2 bootloader,
built from its source. "Factory" means first install/recovery; it is separate from
ST's built-in ROM bootloader. Main menu **3** flashes an existing compiled HEX
without rebuilding. **4** compiles your current edited source, then flashes the new
combined HEX. For later application changes, choose **2** to build, then **5** to
update over USB while keeping the installed loader.

**Hardware status:** ARM GCC builds and host tests pass. On one bench board
(STM32H743 rev V), the UF2 loader enumerated and installed several application
updates with build-ID verification. Power-loss recovery and other boards still
need physical testing.

**Quick commands:** [Windows](../../Flash/Windows/README.md) ·
[Linux](../../Flash/Linux/README.md). Named launchers are in the top-level
`Flash/` folder. Start with `FreeEEG32.cmd` or `bash FreeEEG32.sh` in the main folder.

Choose **5** for USB updates or **6** for the settings menu. Both detect the board
automatically; multiple boards require a selection. USB updates also find the UF2
drive, check the file before upload, and verify the running build ID after restart
before resuming streaming. A board already in UF2 mode can be updated directly.
The settings menu shows rate/gains and saved state, with explicit save/load and
start/stop actions. Close EEG software before either action. Menu **7-11** adds
board/recording checks, support reports and settings files.
[Helper commands and limits](../../Flash/HELPERS.md)

## Windows: automatic setup and build/flash

Use the **[Windows command guide and named launchers](../../Flash/Windows/README.md)**
for source builds, precompiled flashing, USB updates and dry-run commands.

The launcher detects Python 3.10+ and Arm GCC. Missing Python/compiler packages
are installed through Windows **winget**. Missing OpenOCD is downloaded as a
portable xPack 0.12.0-7 archive into `.tools/` and checked against the publisher's
pinned SHA256 before extraction. It does not replace USB drivers automatically.
If a probe is not recognized, install ST's
[ST-Link USB driver](https://www.st.com/en/development-tools/stsw-link009.html)
or the drivers bundled with CubeProgrammer. Winget itself comes with Windows
[App Installer](https://learn.microsoft.com/windows/package-manager/winget/).

Serial-update helpers use a local `.venv` with `pyserial==3.5`. Tool setup does
not flash hardware. `flash` / `build-flash` program through SWD; `usb-update`
installs firmware over USB. A plain `build` compiles
without touching the board. `flash.cmd` also supports dropping a HEX/BIN/ELF onto
it and automatically invokes the flash tooling setup.

## Linux: automatic setup and build/flash

Use the **[Linux command guide and named launchers](../../Flash/Linux/README.md)**
for source builds, precompiled flashing, USB updates and dry-run commands.

Missing packages are installed through apt with sudo: Python/venv, OpenOCD, and
(for source builds only) `gcc-arm-none-eabi` plus newlib. The host serial package
is installed in `.venv`, not into system Python. Other Linux distributions can
install those tools through their own package manager and use the Python commands
below. Their automatic package installation is not implemented.

OpenOCD's packaged udev rules normally provide probe access. If permission is
denied, install the packaged `60-openocd.rules` into `/etc/udev/rules.d/`, reload
udev rules, and reconnect the probe. For serial access, add your account to the
distribution's serial-access group (usually `dialout`) and log in again. Do not run
an entire source build as root just to access the probe.

## Using only a precompiled release

Extract `freeeeg32-uf2-release.zip`, keep its `tools/` folder, and run its
`FreeEEG32.cmd` or `bash FreeEEG32.sh`. The flash and USB-update commands above
work in that folder too. Source-build actions require the repository checkout.
Every UF2 build produces a ZIP. Default 80 MHz builds also refresh the tracked
`Precompiled/` downloads. After pushes to `master`, successful firmware and helper
checks refresh that folder and the
[rolling beta release](https://github.com/joshbrew/FreeEEG32-beta-firmware-upgrade/releases/tag/latest-beta).
Other clock profiles are kept as workflow artifacts. Generated build intermediates
remain ignored. Pull the automatic download commit before your next push.

### CPU clock profiles

Use the main-folder menu to choose **40, 80, 160, 240, 320, 400 or 480 MHz**.
Press Enter to keep **80 MHz**. Advanced commands accept `-CpuMHz N` on Windows
or `--cpu-mhz N` on Linux; direct Python builds use `--cpu-mhz N` too.

| CPU requested | AHB | APBs | Voltage scale | Notes |
| --- | --- | --- | --- | --- |
| 40 MHz | 40 MHz | 20 MHz | VOS3 | Lower CPU clock |
| 80 MHz | 40 MHz | 20 MHz | VOS3 | Default |
| 160 MHz | 40 MHz | 20 MHz | VOS3 | |
| 240 MHz | 60 MHz | 30 MHz | VOS2 | One flash wait state |
| 320 MHz | 40 MHz | 20 MHz | VOS1 | |
| 400 MHz | 50 MHz | 25 MHz | VOS1 | Maximum offered for non-V revisions |
| 480 MHz | 60 MHz | 30 MHz | VOS0 | Rev V only; other revisions automatically use 400 MHz |

The startup config adjusts PLL1, voltage scaling and flash latency together.
USB stays at 48 MHz; SPI/SAI/UART kernel clocks, PLL1Q/R (80 MHz), and the external
8.192 MHz ADC oscillator stay independent of CPU selection. `!RATE` still selects
sampling rate. AHB stays above the USB controller's 30 MHz minimum. The recovery
loader always uses its own fixed 80 MHz profile.

`!INFO` reports actual CPU/AHB speeds, requested MHz and silicon revision.
For 480 MHz it checks for revision V (`0x2003`) before enabling VOS0; any other
revision uses the 400 MHz configuration. The manifest records the request and
fallback. Higher clocks may increase heat/power; they do not increase the selected
ADC sample rate. Start at 80 MHz and compare `!DIAG`/`!STATUS` and temperature before
choosing a higher profile. All profiles require physical timing/USB/thermal testing.

A clock change requires rebuilding and updating the application. Precompiled images
keep their compiled profile. Each build replaces the normal output files, so save
the ZIP/manifest if retaining several grades.

[ST revision/speed limits](https://community.st.com/stm32-mcus-60/how-to-reach-480mhz-for-stm32h7xx-mcus-260) ·
[ST clock, voltage and flash reference](https://www.st.com/resource/en/reference_manual/dm00314099-stm32h742-stm32h743753-and-stm32h750-value-line-advanced-armbased-32bit-mcus-stmicroelectronics.pdf) ·
[ST clarification: VOS0 supports ordinary Sleep, not Stop/Standby](https://community.st.com/stm32-mcus-products-25/running-stm32h745-at-480-mhz-and-using-wfi-31218)

| Image | Purpose |
| --- | --- |
| `freeeeg32-factory.hex` | **First install / recovery:** loader + matching application + app commit record; invalidates a previous staged update |
| `freeeeg32-application.uf2` | **Normal USB updates:** drag onto FREEEEG32; never onto the POWER connector |
| `freeeeg32-application.hex` | SWD application update preserving the loader and invalidating stale staged metadata |
| `freeeeg32-bootloader.hex` | Loader-only maintenance; does not include a working application |
| `manifest.json` | Build ID, image sizes, SHA256 hashes, layout and validation status |

Never flash the standalone `Firmware/build/release/freeeeg32-beta.hex` over a
UF2 installation: it starts at `0x08000000` and would replace the loader. UF2
applications start at `0x08020000`. Generic BIN-to-UF2 conversion is insufficient;
this loader requires the FreeEEG32 board/layout header and image manifest produced
by this build. It ignores ordinary filesystem metadata files.
The raw BIN under `application/` is a build intermediate without a commit record;
use the packaged application HEX or UF2 for updates.

## Manual commands / existing toolchains

Python 3.10+, Arm GNU Toolchain and OpenOCD 0.12+ are sufficient.
These lower-level Python commands expect
tools already installed; the launchers above perform automatic setup.

```bash
python Firmware/UF2/build.py
python Firmware/UF2/build.py --gcc-dir "/path/to/arm-gnu/bin"
python Firmware/Beta/flash.py Firmware/build/uf2/freeeeg32-factory.hex --backend openocd
python Firmware/Beta/flash.py Firmware/build/uf2/freeeeg32-factory.hex --backend cube
python Firmware/Beta/flash.py Firmware/build/uf2/freeeeg32-factory.hex --backend openocd --dry-run
python Firmware/Beta/control.py --list
python Firmware/Beta/control.py --port COM5 BOOTLOADER
```

Use `python3` on Linux where `python` is not provided. An existing compiler can
also be selected with `FREEEEG32_GCC_DIR`. `--openocd PATH`, `--programmer PATH`
and `--serial PROBE_SERIAL` select nonstandard installations/probes. OpenOCD can
also use a CMSIS-DAP probe via `--probe cmsis-dap`.

OpenOCD connects through ST-Link at 1 MHz under reset. Connect **NRST** as well
as SWDIO/SWCLK.
If your dongle lacks working STM32 NRST, use `-Connect normal` on the Windows
launcher or `--connect normal` on Linux/direct Python flash commands. This uses
normal SWD attachment and software reset; recovery from SWD-blocking firmware
still requires a probe with working NRST.

## Wiring and entry

Connect **SWDIO to PA13**, **SWCLK to PA14**, **NRST to RESET**, and **GND to
the GND pad above BOOT**. The **5 V** power pad is just above that GND pad.
The unused square SWD-header pad is PB2, not ground.

Connect target ground separately. If your probe has a documented VTref input,
connect that input to the measured **3.3 V I/O supply**, not the photo's 5 V pad.
The dongle's power-output pins below are not VTref. Power the target normally. Check the actual PCB revision's
continuity; flipping the board mirrors header positions. See the
[updated photo and pin table](../../README.md#swd-programming).

![Pictured ST-Link V2 10-pin dongle](../../SetupGuides/images/st-link-v2-reference.jpg)

For **this printed pinout**: pin 4 SWDIO → PA13; pin 2 SWCLK → PA14; pin 5 or 6 GND →
separate target GND. Pin 1 RST → NRST only if it is verified STM32 NRST; on some
clones it is SWIM reset only. Otherwise leave RST disconnected and select normal
connection as above. Leave SWIM and the dongle's 3.3 V / 5 V output pins disconnected
when the board is powered normally. They are not a documented VTref input.

After factory installation:

- `!BOOTLOADER` acknowledges over CDC, saves a backup-register request and resets
  into the USB drive. The standalone SWD-only firmware returns an error instead.
- Two resets within the loader's **600 ms** startup window enter the drive without
  a working application command. The board's BOOT button selects factory ROM boot
  and is not the UF2 entry button; leave normal flash boot selected.
- A missing/invalid app or failed pending installation stays in the USB loader.
- If an application update fails, reset and copy the complete UF2 again. During a
  verified install, reset/power loss retries the intact bank-2 stage on next boot.

**Why not factory DFU?** ST's ROM USB DFU uses PA11/PA12 on this MCU; this PCB's USB
connector uses PB14/PB15 and PA11/PA12 are on CTS/RTS nets. Software cannot reroute
those signals. Our resident loader configures PB14/PB15 itself. Therefore it needs
a first SWD install, after which the existing connector supports USB updates.

The drive exposes `INFO_UF2.TXT` and `STATUS.TXT`. The Windows/Linux update launchers
check the mounted drive's board ID before copying. After a verified upload and
1.5 seconds without storage writes, it disconnects and resets to install. Allow
several seconds for flash erases and restart. The mount is a synthetic update disk,
not general-purpose storage; copied files do not persist as normal files.

## Flash layout and recovery

| Address range | Use |
| --- | --- |
| `0x08000000–0x0801FFFF` | 128 KB resident loader, bank 1 sector 0 |
| `0x08020000–0x080DFFFF` | Up to 768 KB application, bank 1 sectors 1–6 |
| `0x080E0000` | App commit record, sector 7 |
| `0x08100000–0x081BFFFF` | Update staging, bank 2 sectors 0–5 |
| `0x081C0000–0x081DFFFF` | Application settings journal; preserved by UF2 and factory images |
| `0x081E0000` | Staged commit record, bank 2 sector 7 |

Every 256-byte payload block has bounds, family, board/layout, block-number/count
and duplicate checks. A received-block bitmap accepts out-of-order writes. The
whole image, board header and vectors must pass before the staged commit record
is written. The application record is invalidated before installation and written
last after readback. No update erase/write can target loader sector 0. This is
software address protection; the installer does not change hardware option bytes.

Flash programming uses aligned 32-byte H743 flash words. Loader reads probe for
double-bit ECC BusFaults left by interrupted writes. The loader has caches disabled,
polls the ST USB stack from main, and performs flash operations outside USB ISR
context. Bank-swap mode and chips without 2 MB flash are rejected for writes.
CRC detects corruption; this is not signed firmware or secure boot.

## Verification and hardware checklist

```bash
python -m unittest discover -s Firmware/Beta/tests -v
python -m unittest discover -s Firmware/UF2/tests -v
cc -std=c11 -Wall -Wextra -IFirmware/UF2/Inc Firmware/UF2/tests/test_update.c Firmware/UF2/Src/uf2_update.c Firmware/UF2/Src/uf2_disk.c -o Firmware/build/test_uf2
Firmware/build/test_uf2
```

The C tests exercise the actual updater with strict one-write-per-flash-word
modeling, reordered/duplicate/missing/bad blocks, CRC rejection, FAT12 reads and
all 51 upload + 51 install power-cut points in a test image, including simulated
ECC read faults. Windows native tests can compile the same sources with MSVC
`cl /std:c11 /I Firmware/UF2/Inc ...`.

Before a hardware release, verify ST-Link install/readback; repeated Windows/Linux
MSC and CDC enumeration; actual UF2 file copy and reboot; both entry methods;
interrupted copies/installs at several stages; and EEG framing/rates/alignment/gain.
The build and packaging tools have not flashed a connected board automatically.

The application retains the default 80 MHz CPU and all sampling rates. It now
uses ordinary interrupt-driven Sleep, instruction caching and a 16-frame USB
queue with batching. `!HELP` lists commands; `!HELP SETTINGS`, `!HELP PRESETS` and
`!HELP DIAG` explain persistence, presets and measured throughput. See the
[application command reference](../Beta/README.md#usb-serial-controls) and
[efficiency/heat checks](../Beta/README.md#efficiency-throughput-and-heat).
Normal updates preserve saved settings in bank 2 sector 6. Physical temperature,
USB throughput and ADC alignment must still be measured.

Primary references: [UF2 format](https://github.com/microsoft/uf2),
[STM32H7 family registry](https://github.com/microsoft/uf2/blob/master/utils/uf2families.json),
[ST bootloader pins](https://www.st.com/resource/en/application_note/an2606-stm32-microcontroller-system-memory-boot-mode-stmicroelectronics.pdf),
[ST flash ECC guidance](https://www.st.com/content/st_com/en/technical-documents/an5342--how-to-use-error-correction-code-ecc-management-for-internal-memories-protection-on-stm32-mcus-stmicroelectronics_asset/chunk-003-topic-an5342-test-ecc-flash.html),
[pinned ST MSC middleware](https://github.com/STMicroelectronics/stm32-mw-usb-device/tree/228c5c57ea7089f9fb647ba9f92e10dabcfebbff).
