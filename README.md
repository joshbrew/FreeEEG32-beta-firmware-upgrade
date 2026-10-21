# FreeEEG32-beta

Firmware and programming tools for the **FreeEEG32 beta / STM32H743ZI** board.
The board streams 32-channel EEG over USB and supports runtime sampling and gain settings.

## Start here

**[Download the precompiled ZIP or factory HEX](Precompiled/README.md)**, or use the
[rolling beta release](https://github.com/joshbrew/FreeEEG32-beta-firmware-upgrade/releases/tag/latest-beta).
After pushes to `master`, successful checks refresh both downloads automatically.
The default 80 MHz ZIP and HEX are also tracked in the repository's `Precompiled/`
folder. Source builds at 80 MHz refresh that folder for your next commit.

**Windows:** double-click **[FreeEEG32.cmd](FreeEEG32.cmd)** in the main folder.

**Linux:** open a terminal in the main folder and run:

```bash
bash FreeEEG32.sh
```

| Menu | Action |
| --- | --- |
| 1 | Install/check all tools |
| 2 | Build firmware from edited source |
| 3 | Flash an existing compiled firmware + UF2 loader with ST-Link |
| 4 | Build edited source, then flash firmware + UF2 loader with ST-Link |
| 5 | Update firmware over USB |
| 6 | Configure sampling, gain and saved settings |
| 7 | Check USB, firmware and ADC settings |
| 8 | Test recording for 10 seconds |
| 9 | Save a support report |
| 10 | Back up settings to a file |
| 11 | Restore settings from a file |

Each action installs missing tools as needed. Setup shows the download source,
installation location and progress. Flashing precompiled firmware, USB updates
and configuration do not require the compiler. Automatic Linux installation
supports Debian/Ubuntu.

Use the source checkout to edit and build firmware. A precompiled release ZIP
contains the launchers and helpers needed to flash, update and configure a board.
[Windows commands](Flash/Windows/README.md) · [Linux commands](Flash/Linux/README.md)

## First installation

1. Connect ST-Link to the [SWD pins below](#swd-programming) and power the board.
2. Choose **4** to compile your edited source and flash it, or **3** to flash an existing `freeeeg32-factory.hex` without compiling.
3. Connect the board's **USB data port** to the computer for EEG streaming and configuration.

**`freeeeg32-factory.hex` is this fork's combined EEG firmware and UF2 bootloader.**
"Factory" means the first-install/recovery package. It is built from this fork's
source and is separate from ST's built-in ROM bootloader.

**Option 3** uses an already compiled HEX from a previous build or an extracted
release ZIP; it does not include source edits made since that build. **Option 4**
compiles the current source, creates a fresh combined HEX and flashes it.
Build outputs are in `Firmware/build/uf2/`; edit application sources in
`Firmware/Beta/Inc` and `Firmware/Beta/Src`. Bootloader sources are in `Firmware/UF2`.

## USB updates

To update after editing source, choose **2** to build, then **5** to install the
new application over USB. The installed UF2 loader stays in place.

Close EEG software using the board, open the launcher and choose **5**.
The helper detects the board, enters update mode, finds its drive and copies
`freeeeg32-application.uf2`. It waits for the board to restart, checks the running
build ID against the selected image, then resumes USB streaming. If several
boards are connected, choose one from the list.

You can also press **RESET twice within 600 ms** and copy the application UF2
onto the **FREEEEG32** drive. The drive disappears when installation completes.
The BOOT button selects the factory ROM loader; use RESET for UF2.

The updater also accepts a board already in UF2 mode. Custom image paths and
port/drive overrides are documented in the [Windows](Flash/Windows/README.md#update-over-usb-after-first-installation)
and [Linux](Flash/Linux/README.md#update-over-usb-after-first-installation) guides.

## Board checks and settings files

Choose **7 — Check my board** to check the USB connection, firmware commands and
all four ADCs' rate/gain registers. Choose **8 — Test recording** to measure
received frames, sample rate and data loss over 10 seconds. This checks data
delivery; it does not assess electrode contact or EEG signal quality.

Choose **9** to save a support report, **10** to back up the current settings,
or **11** to preview and restore a settings file. Restore can apply settings for
the current session or save them for power-up. Invalid files are rejected before
changing settings. A failed restore leaves acquisition paused.

Checks and backups briefly pause acquisition and restore its previous running or
paused state. Reports and backups are saved in `reports/`; support reports include
versions, settings and error counters, without EEG samples. Configuration hides
technical replies by default; choose **A** for advanced details.
[Helper commands and report details](Flash/HELPERS.md)

## Sampling and gain

Choose **6 — Configure board**. The menu shows the current sample rate, all 32
channel gains and whether changes have been saved. Available settings:

- Sampling: **512, 1024 or 2048 Hz**.
- Gain: **1, 2, 4 or 8**, for one channel or all channels.
- Presets: DEFAULT (512 Hz / gain 8), FAST (2048 Hz / gain 8), LOWGAIN (1024 Hz / gain 1).
- Save, load or restore factory settings; view status and diagnostics.

Configuration pauses acquisition. Choose **Save settings** to keep changes after
power-up, then **Start streaming and exit** to resume. Closing the menu without
saving leaves changes in RAM. Factory defaults are 512 Hz and gain 8.
The menu prompts about unsaved changes before you leave.

For serial-terminal use, send **`!HELP`**. Commands end with a newline;
`!START` resumes acquisition after a command.
[Full command reference](Firmware/Beta/README.md#usb-serial-controls)

## SWD programming

Connect the ST-Link signals to these board pins:

- **SWDIO → PA13**
- **SWCLK → PA14**
- **NRST → RESET**
- **GND → GND pad above BOOT**

The unused square pad on the SWD header is PB2, **not ground**.
Power the board through its normal supply and keep electrodes disconnected while
programming. A probe's VTref/VAPP input connects to the measured **3.3 V target
I/O supply**. The 5 V board pad is a power connection, not VTref.

![FreeEEG32 connections: 5 V and GND above BOOT; SWCLK, SWDIO and NRST below RESET](SetupGuides/images/basic_layout_swd.png)

### ST-Link V2 dongle

![ST-Link V2 dongle with its printed 10-pin connector legend](SetupGuides/images/st-link-v2-reference.jpg)

Use the numbers printed on your probe; clone connector layouts vary.

| Pin on this dongle | Board connection |
| --- | --- |
| **4 — SWDIO** | **PA13 / SWDIO** |
| **2 — SWCLK** | **PA14 / SWCLK** |
| **5 or 6 — GND** | **GND above BOOT** |
| **1 — RST** | **NRST / RESET**, if the probe supports STM32 reset |
| 3 — SWIM | Leave disconnected |
| 7 / 8 — 3.3 V; 9 / 10 — 5 V | Leave disconnected when the board is powered separately; these are power outputs |

Some dongles provide SWIM reset only. If STM32 NRST is unavailable, use
`-Connect normal` on Windows or `--connect normal` on Linux for a normally booting
board. Recovery from firmware that blocks SWD needs a probe with working STM32 NRST.
[ST-Link connector reference](https://www.st.com/resource/en/user_manual/dm00026748-st-link-v2-in-circuit-debugger-programmer-for-stm8-and-stm32-stmicroelectronics.pdf)
· [Detailed wiring guide](SetupGuides/FreeEEG32_Programming_and_Updates.md)

## Features added by this fork

| Feature | Details |
| --- | --- |
| USB firmware updates | Install the UF2 loader once through SWD, then update through the USB data port |
| Build and flash launchers | Windows/Linux menus, automatic tool installation and precompiled-image support |
| Board detection and update checks | Automatic serial/drive selection and running-build verification after USB updates |
| Settings menu and serial commands | Sample rate, per-channel gain, presets, explicit save/load and command help |
| Board and recording checks | ADC register readback, measured USB delivery rate, frame-loss checks and saved support reports |
| Settings files | Validated backup/restore with a preview and explicit save choice |
| Hang recovery | Main-loop watchdog; reset reason and ADC fault details in diagnostics |
| CPU clock selection | 40/80/160/240/320/400/480 MHz build profiles; 80 MHz default |
| Acquisition and transfer fixes | Eight-word ADC DMA reads, timeouts, USB frame buffering, batching and drop counters |
| CPU idle sleep | Optional build setting, off by default; DMA, acquisition and USB clocks continue while the CPU waits for interrupts |
| Update recovery | Board/layout checks, image CRC verification and staged installation with retry after interrupted writes |

Sample rate is independent of the CPU clock profile. The 480 MHz profile requires
revision V silicon and falls back to 400 MHz on other revisions. Use USB for
complete streams above 512 Hz; UART bandwidth is limited.
[Clock profiles](Firmware/UF2/README.md#cpu-clock-profiles)

**Hardware status:** firmware builds and host simulations pass. One board
(STM32H743 rev V, Windows 11) has been bench-tested at 512 Hz: SWD flashing with
an STLINK-V3MINIE, USB enumeration and replug, UF2 updates, `Check my board` and a
10 s test recording (512 Hz, no missing frames or DMA errors). Other rates,
sustained throughput, temperatures and other boards still need testing.

## Why ROM DFU cannot use this USB connector

The USB data connector is wired to **PB14/PB15**. ST's ROM DFU loader uses
**PA11/PA12**, which this board assigns to UART CTS/RTS. The custom UF2 loader
uses PB14/PB15 and must be installed through SWD before USB updates are available.
[ST bootloader pin reference](https://www.st.com/resource/en/application_note/an2606-stm32-microcontroller-system-memory-boot-mode-stmicroelectronics.pdf)

## Files and documentation

- [Flash/Windows](Flash/Windows/README.md) / [Flash/Linux](Flash/Linux/README.md): command launchers and options.
- [Firmware](Firmware/README.md): application, loader, build inputs and tooling.
- [SetupGuides](SetupGuides/README.md): wiring and integration guides.
- [AssemblyFiles](AssemblyFiles/README.md): PCB, Gerbers and BOM.
- [OpenViBE integration](SetupGuides/FreeEEG32_OpenVibe_Docker_Readme.md).

Generated builds are in `Firmware/build/`; downloaded tools and Python helpers
are in `.tools/` and `.venv/`.
Successful builds are also kept in dated folders under `Firmware/build/history/`,
with the clock profile, build ID, firmware package and manifest.

[Upstream](https://github.com/neuroidss/FreeEEG32-beta) ·
[Crowd Supply](https://www.crowdsupply.com/neuroidss/freeeeg32) ·
[BrainFlow](https://brainflow.readthedocs.io/en/stable/) ·
[Web application](https://github.com/moothyknight/eegpwa)
