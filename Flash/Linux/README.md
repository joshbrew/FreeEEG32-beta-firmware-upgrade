# Linux: build, flash and USB update

Run from the repository root. Use `bash` explicitly; executable permission is not
required. Missing tools are installed automatically on **Debian/Ubuntu** using
apt and sudo; serial helpers use a local `.venv`. Other distributions need their
own package manager for Python/venv, Arm GCC/newlib and OpenOCD.

Before downloading, setup prints missing packages, their purpose, source and
destination. apt shows dependency details, sizes and progress; its metadata refresh
is labeled separately. Python packages use pip's configured index (PyPI by default)
and are installed into `.venv`. The installed/reused summary is saved in
`.tools/setup-summary.txt`. **Install-tools / menu option 1 installs all tools;
flash-precompiled skips the compiler.**

## First install: build and flash with ST-Link

This compiles the current edited source and flashes both this fork's EEG firmware
and UF2 bootloader as `freeeeg32-factory.hex` (main menu **4**). "Factory" means
the combined first-install/recovery image built from this fork.

Wire [SWDIO, SWCLK, ground and verified STM32 NRST](../../README.md#swd-programming),
power the board normally, then run:

```bash
bash Flash/Linux/build-and-flash.sh --backend openocd
```

If probe access is denied, install the packaged OpenOCD udev rules and reconnect
the probe. For serial access, your account may need the `dialout` group and a new
login session. [Permissions and prerequisites](../../Firmware/UF2/README.md#linux-automatic-setup-and-buildflash).
Do not run the entire source build as root to work around device permissions.

## Build edited source without flashing

```bash
bash Flash/Linux/build.sh
bash Flash/Linux/build.sh --cpu-mhz 40
```

80 MHz is the default. Grades: 40/80/160/240/320/400/480 MHz. The 480 MHz grade
requires revision V; other revisions use 400 MHz. Higher clocks need thermal and
throughput testing. See the [profile details](../../Firmware/UF2/README.md#cpu-clock-profiles).
Edit `Firmware/Beta/Inc` / `Src`, not generated `Firmware/build/source`.
UF2, factory HEX, manifest and release ZIP appear in `Firmware/build/uf2/`.

## Flash a precompiled image

This flashes an existing file without compiling (main menu **3**). Source edits
made after that file was built are not included. The default factory HEX contains
both this fork's EEG firmware and UF2 bootloader.

```bash
bash Flash/Linux/flash-precompiled.sh ~/Downloads/freeeeg32-factory.hex --backend openocd
# Inspect the command without writing hardware:
bash Flash/Linux/flash-precompiled.sh ~/Downloads/freeeeg32-factory.hex --backend openocd --dry-run
```

Without an image argument, the helper selects the local build, then
`Precompiled/freeeeg32-factory.hex` on a fresh source clone (or the bundled factory
HEX in a release ZIP). No compiler is needed. Prefer HEX because it carries
its addresses. Use factory HEX for first install/recovery and application UF2
for normal updates.

For a dongle **without working STM32 NRST**, leave its RST disconnected and add
`--connect normal` for normal SWD attachment with software reset:

```bash
bash Flash/Linux/build-and-flash.sh --backend openocd --connect normal
```

Normal connection cannot recover every broken firmware image; under-reset recovery
requires a probe with verified NRST. The pictured dongle's RST may be SWIM-only.

## Update over USB after first installation

Close other software using the serial port. The helper detects the board and
its UF2 mount automatically; if several boards are connected, select one.

```bash
bash Flash/Linux/usb-update.sh
# Choose another precompiled UF2:
bash Flash/Linux/usb-update.sh --image ~/Downloads/freeeeg32-application.uf2
# Override detection if needed:
bash Flash/Linux/usb-update.sh --port /dev/ttyACM0
# Board already in UF2 mode:
bash Flash/Linux/usb-update.sh --drive "/media/$USER/FREEEEG32"
```

The helper validates the image, requests the loader, checks the drive identity,
copies the file and waits for restart. It checks that the running build matches
the image, then resumes EEG streaming. A successful copy alone is not reported
as a verified update. Images need a build ID from the current build tools for
this check; images without one can be copied manually. Enable desktop USB
automount or mount the drive yourself and pass `--drive`.

Alternatively press **RESET twice within 600 ms**
and copy the application UF2 onto **FREEEEG32**. Do not use the BOOT button.

## Configure the board

Choose **6** in `bash FreeEEG32.sh`, or run:

```bash
bash Flash/Linux/configure.sh
bash Flash/Linux/configure.sh --port /dev/ttyACM0
```

The menu shows the current rate, gains and saved state. Set 512/1024/2048 Hz,
change one/all channel gains, apply a preset, save/load settings or view diagnostics.
Acquisition is paused during configuration. Saving is explicit; choose **Start
streaming and exit** when finished. This action installs only Python/USB helper
dependencies, without the compiler or OpenOCD.

## Board checks, recording tests and settings files

Use menu **7-11**, or the **check-board**, **test-recording**, **support-report**,
**backup-settings** and **restore-settings** `.sh` files in this folder. Reports
and backups default to `reports/`. Restores show a preview before applying changes.
[Commands, options and test limits](../HELPERS.md)

## Tool setup and USB help

```bash
bash Flash/Linux/install-tools.sh
bash Flash/Linux/menu.sh
.venv/bin/python Firmware/Beta/control.py --port /dev/ttyACM0 HELP
.venv/bin/python Firmware/Beta/control.py --port /dev/ttyACM0 "HELP SETTINGS"
```

In a release bundle the helper is `control.py` in the bundle root. Commands pause
streaming; add `--resume` to restart afterward.
[All controls](../../Firmware/Beta/README.md#usb-serial-controls).
