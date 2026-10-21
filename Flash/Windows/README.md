# Windows: build, flash and USB update

Run these commands in PowerShell or Command Prompt **from the repository root**.
The `.cmd` files in this folder can also be double-clicked. `Menu.cmd` lets you
choose an action; action launchers retain the result on screen when run without
arguments. Flash actions write the connected board; build/setup actions do not.

## First install: build and flash with ST-Link

This compiles the current edited source and flashes both this fork's EEG firmware
and UF2 bootloader as `freeeeg32-factory.hex` (main menu **4**). "Factory" means
the combined first-install/recovery image built from this fork.

Wire [SWDIO, SWCLK, ground and verified STM32 NRST](../../README.md#swd-programming),
power the board normally, then run:

```powershell
.\Flash\Windows\Build-and-Flash.cmd -Backend openocd
```

Missing Python 3.10+/Arm GCC are installed through winget. Missing OpenOCD is
downloaded to `.tools/` with a pinned SHA256 check. Setup may need elevation;
ST-Link USB drivers are installed separately if Windows does not recognize the probe.
[Complete prerequisites and driver instructions](../../Firmware/UF2/README.md#windows-automatic-setup-and-buildflash).

Before downloading, setup prints the tool, purpose, source and installation location.
winget shows the resolved version, exact installer URL, download size and progress.
The Arm toolchain is a large compiler/debugger/runtime package for source builds.
**Install-Tools / menu option 1 installs all tools; Flash-Precompiled skips the
compiler.** Existing tools are reused. The final installed/reused summary is saved
in `.tools/setup-summary.txt`.

## Build edited source without flashing

```powershell
.\Flash\Windows\Build.cmd
.\Flash\Windows\Build.cmd -CpuMHz 40
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

```powershell
.\Flash\Windows\Flash-Precompiled.cmd -Image "C:\Downloads\freeeeg32-factory.hex" -Backend openocd
# Inspect the command without writing hardware:
.\Flash\Windows\Flash-Precompiled.cmd -Image "C:\Downloads\freeeeg32-factory.hex" -Backend openocd -DryRun
```

You can drag a HEX/BIN/ELF onto `Flash-Precompiled.cmd`. Without an image argument,
the helper selects the local build, then `Precompiled/freeeeg32-factory.hex`
on a fresh source clone (or the bundled factory HEX in a release ZIP).
No compiler is needed for this action. Prefer HEX because it carries its addresses.
Use the factory HEX for first install/recovery and application UF2 for normal updates.

For a dongle **without working STM32 NRST**, leave its RST disconnected and add
`-Connect normal` for normal SWD attachment with software reset:

```powershell
.\Flash\Windows\Build-and-Flash.cmd -Backend openocd -Connect normal
```

Normal connection cannot recover every broken firmware image; under-reset recovery
requires a probe with verified NRST. The pictured dongle's RST may be SWIM-only.

## Update over USB after first installation

Close other software using the serial port. The helper detects the board and
its UF2 drive automatically; if several boards are connected, select one.

```powershell
.\Flash\Windows\USB-Update.cmd
# Choose another precompiled UF2:
.\Flash\Windows\USB-Update.cmd -Image "C:\Downloads\freeeeg32-application.uf2"
# Override detection if needed:
.\Flash\Windows\USB-Update.cmd -Port COM5
# Board already in UF2 mode:
.\Flash\Windows\USB-Update.cmd -Drive E:\
```

The helper validates the image, requests the loader, checks the drive identity,
copies the file and waits for restart. It checks that the running build matches
the image, then resumes EEG streaming. A successful copy alone is not reported
as a verified update. Images need a build ID from the current build tools for
this check; images without one can be copied manually.

Alternatively press **RESET twice within 600 ms**
and drag the application UF2 onto **FREEEEG32**. Do not use the BOOT button.

## Configure the board

Choose **6** in `FreeEEG32.cmd`, or run:

```powershell
.\Flash\Windows\Configure.cmd
.\Flash\Windows\Configure.cmd -Port COM5
```

The menu shows the current rate, gains and saved state. Set 512/1024/2048 Hz,
change one/all channel gains, apply a preset, save/load settings or view diagnostics.
Acquisition is paused during configuration. Saving is explicit; choose **Start
streaming and exit** when finished. This action installs only Python/USB helper
dependencies, without the compiler or OpenOCD.

## Board checks, recording tests and settings files

Use menu **7-11**, or the **Check-Board**, **Test-Recording**, **Support-Report**,
**Backup-Settings** and **Restore-Settings** `.cmd` files in this folder. Reports
and backups default to `reports/`. Restores show a preview before applying changes.
[Commands, options and test limits](../HELPERS.md)

## Tool setup and USB help

```powershell
.\Flash\Windows\Install-Tools.cmd
.\Flash\Windows\Menu.cmd
python Firmware/Beta/control.py --port COM5 HELP
python Firmware/Beta/control.py --port COM5 "HELP SETTINGS"
```

Tool setup creates `.venv` with pyserial. If `python` is not on your shell's PATH,
use `.\.venv\Scripts\python.exe` for the helper. In a release bundle, its helper
is `control.py` in the bundle root. Commands pause streaming; add `--resume` to
restart afterward. [All controls](../../Firmware/Beta/README.md#usb-serial-controls).
