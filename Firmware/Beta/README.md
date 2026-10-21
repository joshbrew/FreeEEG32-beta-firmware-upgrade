# FreeEEG32 application firmware

This is the maintained build entry point for the **STM32H743ZI beta board at
40–480 MHz in selectable grades (default 80)**, based on the existing `STM32H743ZI_beta_80MHz_makefile.tar.gz` archive.
The build is verified with Arm GCC 9.2.1 and 14.2.1; **USB enumeration, sampling accuracy,
four-ADC alignment and flashing still need testing on physical hardware**.

For normal use, start with the [UF2 build and automatic Windows/Linux launchers](../UF2/README.md).
The platform-specific commands are in [Flash/Windows](../../Flash/Windows/README.md)
and [Flash/Linux](../../Flash/Linux/README.md).
`python Firmware/Beta/build.py` below builds a standalone SWD image at
`0x08000000`; it replaces an installed UF2 loader. The UF2 build reuses these edited
sources and links its application at `0x08020000` instead.

## Build

Install Python 3.10+ and Arm GNU Toolchain. From the repository root:

```powershell
python Firmware/Beta/build.py
# Optional lower CPU clock for the standalone SWD image
python Firmware/Beta/build.py --cpu-mhz 40
```

If the compiler is not on PATH:

```powershell
python Firmware/Beta/build.py --gcc-dir "C:/path/to/toolchain/bin"
```

This works without make, Docker, AC6, or downloads during the build. It validates
the base archive's SHA256, extracts sources into ignored `Firmware/build/source`,
using the pinned input in `Firmware/Base/`,
applies checked source transformations from `prepare.py`, and overlays `Inc/` and
`Src/`. Edit the Beta files, not generated sources. Existing vendor notices are
retained in the generated source tree. The base archive remains versioned so the
build does not depend on a changing remote SDK.

`--cpu-mhz N` selects 40/80/160/240/320/400/480 MHz; all sources are rebuilt
on each invocation. The profiles keep AHB at 40–60 MHz and APBs at 20–30 MHz, preserve USB's
48 MHz HSI48 source and leave the external ADC clock unchanged. Edit
`Inc/clock_profile.h` only when adding a carefully validated profile; unsupported
values are rejected by both the build command and the C preprocessor. The board's
OTG_HS bus must remain above 30 MHz. See the
[UF2 clock profile notes](../UF2/README.md#cpu-clock-profiles) for limitations.
The manifest records the profile and `!INFO` reports runtime CPU/AHB frequencies.
Builds also record a deterministic source/compiler/flag fingerprint. The same
build ID is embedded in the application and returned by `!INFO`; the USB updater
uses it to check the running firmware after installation.

Outputs in `Firmware/build/release/`:

| File | Use |
| --- | --- |
| `freeeeg32-beta.hex` | Recommended for programming; includes addresses |
| `freeeeg32-beta.bin` | Raw image at `0x08000000` |
| `freeeeg32-beta.elf` | Debugging and programming |
| `manifest.json` | Board, version, compiler and image sizes/SHA256 hashes |
| `warnings.log` | Compiler diagnostics, including inherited legacy warnings |

No bootloader offset is reserved by this build. These images replace the
application at `0x08000000`; they are not UF2 or offset bootloader applications.

## Flash

Install STM32CubeProgrammer and wire a genuine ST-Link directly to the board's
SWDIO, SWCLK, NRST, GND and target voltage reference. Power the board separately.
See the [wiring and recovery guide](../../SetupGuides/FreeEEG32_Programming_and_Updates.md).

```powershell
python Firmware/Beta/flash.py
python Firmware/Beta/flash.py "path/to/firmware.hex"
python Firmware/Beta/flash.py "path/to/firmware.bin" --dry-run
```

On Windows, drop the compiled file onto `Firmware/Beta/flash.cmd`, or double-click
it to flash the latest build. **This is a PC shortcut using an attached ST-Link.**
The board does not appear as a USB drive. The helper connects under hardware
reset at 1 MHz, writes, verifies, and resets. With multiple probes, specify
`--serial STLINK_SERIAL`. Use `--programmer PATH` for a nonstandard installation.

## USB controls

Menu **7-11** provides ADC checks, a timed recording check, support reports and
settings-file backup/restore. [Helper guide](../../Flash/HELPERS.md)

For interactive configuration, run the main launcher and choose **6**. It detects
the board and provides rate, gain, presets, explicit save/load, diagnostics and
start/stop controls. Close EEG software before opening configuration; commands
pause acquisition until you choose **Start streaming and exit**.

The device uses USB CDC ACM with VID/PID `0483:5740` and a UID-based
serial descriptor. Its product name is `FreeEEG32 EEG + Control`. The USB peripheral
named HS operates at **USB full speed through its embedded PHY on PB14/PB15**.
Windows 10/11 should use the built-in USB serial driver. Enumeration on a board
must still be confirmed. The firmware stores and returns line coding, handles
control-line requests, disciplines HSI48 from USB2 SOF through CRS, and rejects
transmissions before configuration or after disconnect. Virtual COM baud settings
do not change the ADC rate.

Install the optional host helper dependency:

```powershell
python -m pip install pyserial
python Firmware/Beta/control.py --list
python Firmware/Beta/control.py
python Firmware/Beta/control.py --port COM5 "RATE 1024" "GAIN 1 4" STATUS --resume
```

Close BrainFlow/OpenViBE/other applications using that port first. The helper
sends STOP and checks the board identity before issuing commands. Without
`--resume`, streaming remains paused.
Opening the port alone does not stop the stream or reset the board.

In any serial terminal, commands start with `!` and end in CR, LF, or CRLF:

| Command | Effect |
| --- | --- |
| `!HELP` | List supported commands |
| `!HELP SETTINGS` / `!HELP PRESETS` / `!HELP DIAG` | Usage, defaults and diagnostic units |
| `!INFO` | Board, firmware/build identity, protocol, runtime CPU/AHB MHz and clock source (`clock=HSE`, or `HSI` if the crystal did not start) |
| `!STATUS` | Rate, complete captures, missed DRDY events, DMA errors, USB/UART drops, RX overflow, ADC fault and `readback_mask` (ADCs whose register readback disagreed with a write) |
| `!CHECK` | Measure DRDY for 500 ms against the selected rate (`drdy_hz`, `rate_ok` within 1 %) and read back the SRC dividers, SINC3 filter selection and gains on all four ADCs; report pass/fail masks and the last failed ADC/register/operation/value |
| `!DIAG` | Last full streaming window's measured rates/sleep wait fraction; maximum observed capture/latency/work times; reset flags |
| `!SETTINGS` | Current rate and all 32 gains; saved/default source and dirty flag |
| `!PRESET DEFAULT` | Apply 512 Hz and gain 8 on all channels; unsaved |
| `!PRESET FAST` | Apply 2048 Hz and gain 8 on all channels; unsaved |
| `!PRESET LOWGAIN` | Apply 1024 Hz and gain 1 on all channels; unsaved |
| `!SAVE` | Explicitly persist verified current rate/gains across power cycles |
| `!LOAD` | Apply saved rate/gains, or defaults if no valid saved record exists |
| `!FACTORY` | Apply 512 Hz/gain 8, erase saved settings and save these defaults |
| `!STOP` | Pause capture and output; report `was_streaming=0` or `was_streaming=1` |
| `!RATE 512` | Set all four AD7771 SRC dividers for 512 samples/s, then resynchronize the ADCs with a START pulse |
| `!RATE 1024` / `!RATE 2048` | Set 1024 / 2048 samples/s |
| `!GAIN 1 4` | Set channel 1 gain to 4; channels 1–32, gains 1/2/4/8 |
| `!START` | Reply `OK START`, then resume acquisition |
| `!REBOOT` | Reply, then reset and load the saved settings, or defaults if none |
| `!BOOTLOADER` | In a UF2 application, reply and reset into the update drive; standalone firmware returns an installation-required error |
| `!SPIREAD 1 17` | Bench diagnostic: raw AD7771 read frames for one register (ADC 1–4, register 0–127, decimal) plus the driver read |
| `!SPIWRITE 1 17 100` | Bench diagnostic: one raw AD7771 register write (value 0–255, decimal); bypasses settings, verification and the driver cache |

Commands are case insensitive. Every prefixed command pauses acquisition,
including invalid commands, and replies only through USB. Start again explicitly
after configuration. Unprefixed traffic, including legacy host commands, is
ignored. Commands run in main, not in USB interrupt context. RX buffers and line
length are bounded. A queue overflow discards the partial command and resynchronizes
at the next newline; resend a complete command after that newline.

Changes live in RAM until **`!SAVE`**. On reboot, the latest valid saved rate/gains
are applied and read back before capture starts. Factory defaults are
high-resolution ADC mode, 512 samples/s and gain 8 on each channel. Rates assume
the schematic's 8.192 MHz oscillator, giving
a 2.048 MHz modulator clock in HR mode. The supported dividers are 4000, 2000 and
1000. **256 samples/s cannot be reached in this HR mode by writing 8000 into the
12-bit divider.** That requires another mode/clock or properly filtered software
decimation. Raw register writes and mode switching are intentionally not exposed.

Rate and gain writes are checked by reading actual hardware registers. Failed
configuration stops streaming and latches an ADC fault until reboot. Changes
discard a 20 ms settling interval. Sequential software SRC loads follow the base
design; phase alignment across the four ADCs after a change needs bench validation.
Host-side sample-rate metadata and filters must be updated to match the new rate.
Some clients hard-code the original rate and need changes outside this repository.

The binary packet remains 105 bytes: `A0`, 8-bit sequence, 32 channels of 24-bit
big-endian samples, six zero auxiliary bytes, `C0`. The auxiliary values were already
placeholders. Sequence advances per acquired output frame, including USB drops.
UART remains at 921600 baud: its theoretical 105-byte packet ceiling is about
877 packets/s, so **1024 and 2048 samples/s require USB for a complete stream**.
Slow UART output drops and increments its counter without blocking USB acquisition.

### Saved settings

Settings use an append-only journal in **bank 2 sector 6, `0x081C0000–0x081DFFFF`**,
which the UF2 loader already excludes from staging. Normal UF2/factory HEX writes
preserve this sector; a whole-chip erase or another firmware's use of this area
does not. The standalone linker reserves the last 256 KB to prevent code overlap.
CPU clock and streaming state are not saved: the clock comes from the compiled
image, and capture starts after startup validation.

Each explicit save writes one 32-byte flash word with schema version, sequence,
rate, packed per-channel gains, CRC32 and its inverse. Saving identical settings
does not write again. Invalid/CRC-failed/ECC-failed records are skipped, preserving
an earlier valid record. There are 4096 record slots; a full journal returns an
error without erasing existing settings. `!FACTORY` explicitly recycles it and
saves defaults. An interrupted factory erase can lose the saved configuration;
boot falls back to valid records or defaults. These are host-tested recovery rules,
not a guarantee of physical brownout behavior. Flash writes never run in an ISR
or during streaming.

### Efficiency, throughput and heat

The default remains **80 MHz CPU / 40 MHz AHB**, now derived from the board's 16 MHz
crystal Y2 (HSE) instead of the internal HSI oscillator; if Y2 does not start, the
firmware falls back to HSI. The ADCs keep their own 8.192 MHz oscillator (U8), and
USB (HSI48 + CRS) and USART1 (HSI) clocks are unchanged. Idle WFI is **off by default**
(`FREEEEG32_IDLE_WFI=0`, `!INFO` reports `idle=spin`): on the bench board the core
stayed in WFI with enabled USB/EXTI interrupts pending. Build with
`-DFREEEEG32_IDLE_WFI=1` to test it. When enabled, WFI uses ordinary **Sleep**,
with acquisition, USB, UART, DMA and SysTick clocks retained. Stop/Standby and
tick suspension are not used. An IRQ-masked work check prevents sleeping over
queued RX, an outstanding DRDY or completed DMA; a newly pending IRQ wakes WFI
before IRQs are unmasked. There is no added millisecond delay or sample throttling.
Instruction cache is enabled to reduce flash fetch work; data cache remains
disabled to preserve DMA coherency. Maintained C modules are compiled with `-O2`;
inherited sources keep their existing debug optimization flags.

The USB path holds up to 16 complete frames and submits contiguous batches of up
to 1680 bytes. Frame format/order remain unchanged; hosts must parse a byte stream
instead of assuming one OS read equals one frame. `usb_dropped` counts queue
overflow, `usb_queued` is the waiting queue depth, and `usb_high_water` is its peak.
`control_discarded` counts an in-progress capture deliberately stopped by a command.
An indefinitely stalled host still exhausts a bounded queue. Close the USB reader
only after collecting throughput measurements; an unread port can create drops.

`!DIAG` reports the last full, approximately one-second **streaming** window:

- `drdy_millihz` / `capture_millihz`: divide by 1000 for Hz. A 2048 Hz stream should
  approach 2048000 in both; compare host-received frames and `!STATUS` drops too.
- `window_us`: actual measurement interval. Before a complete window, rate fields
  are zero. Pausing/configuring does not overwrite the last completed window.
- `max_capture_us`: maximum observed DMA-start-to-main-completion time;
  `max_latency_us`: latest DRDY timestamp to capture start; `max_work_us`: longest
  main-loop work interval while streaming. These include scheduling effects and
  are not a hard real-time guarantee. Compare them with 488 microseconds at 2048 Hz.
- `wait_permille`: time spent inside masked WFI waits per 1000 window time units;
  **not measured CPU utilization**. `sleep_entries` counts sleep attempts.
- `reset_flags`: raw STM32 RCC reset flags in hex. The updated UF2 loader forwards
  the original flags via backup registers 26/27; older loaders may report zero.

TIM2 is reserved as a free-running 1 MHz diagnostic clock, including during Sleep.
Timestamp differences handle its 32-bit wrap; counters are not a temperature sensor.
HELP/INFO/STATUS/DIAG also pause acquisition to keep text separate from EEG packets.
Use `!START` afterward; sample-rate/gain changes are always explicit.

To check a hot board, compare old/new firmware at **80 MHz and the same rate**,
with a host continuously draining USB. Record input current, measured package
temperature, `!DIAG` rates and `!STATUS` drops, then compare stopped acquisition.
The source clock is not proof of the image currently installed: query `!INFO`.
If it remains hot with the CPU mostly waiting, check supply voltages and identify
whether the MCU, regulator or converters are producing the heat before attributing
it to firmware. Do not claim a power/noise improvement without measurements.
[ST Cortex-M7 Sleep/WFI reference](https://www.st.com/resource/en/programming_manual/pm0253-stm32f7-series-and-stm32h7-series-cortexm7-processor-programming-manual-stmicroelectronics.pdf).

## Reliability changes

- Read eight 32-bit words per ADC. The legacy code passed `SAI_DATASIZE_32`, a
  register bitmask equal to **224**, into the DMA transfer-length argument for a
  32-byte buffer. All legacy DMA call sites are corrected too.
- Wait for all four DMA transfers to complete before publishing a frame. Bound
  stalled transfers to 10 ms, inspect SAI errors, stop/flush FIFOs between frames,
  and count missed events. The ISR only marks ADC1 DRDY events.
- Keep USB and UART transmission buffers unchanged while their transfers are
  active. Queue/batch USB frames through temporary backpressure; count bounded
  queue overflow and UART busy drops without spinning on either transport.
- Fix an uninitialized ADC setup pointer/status, zero-initialize device state,
  preserve integer/fractional divider caches, propagate SPI errors, use 16-bit GPIO
  masks, and bound SPI register transactions to 20 ms.
- Mark DMA scratch SRAM `NOLOAD` in the linker script. Otherwise raw binary export
  spans the flash-to-SRAM address gap and produces a roughly 640 MB file. The build
  rejects images larger than the STM32's flash.
- Supply a bounded newlib heap so USB class allocation and ADC setup do not use
  libnosys' always-failing `_sbrk` stub.
- Skip unconditional optional SD-card initialization through BSP; acquisition
  does not require inserting a card. The generated peripheral initialization remains.

These address specific defects; they do not establish the cause of every reported
duplicate sample. The older optional DSP/SD/output modes are not exercised by this
new default loop and still have inherited compiler warnings.

## Verification

```powershell
python -m unittest discover -s Firmware/Beta/tests -v
```

The C simulation exercises the real command parser and acquisition/control module
against hardware mocks. With GCC/Clang:

```sh
cc -std=c11 -O2 -Wall -Wextra -IFirmware/Beta/tests/mocks -IFirmware/Beta/Inc Firmware/Beta/tests/test_firmware.c Firmware/Beta/Src/control_protocol.c Firmware/Beta/Src/settings.c -o Firmware/build/test_firmware
Firmware/build/test_firmware
cc -std=c11 -O2 -Wall -Wextra -IFirmware/Beta/Inc Firmware/Beta/tests/test_settings.c Firmware/Beta/Src/settings.c -o Firmware/build/test_settings
Firmware/build/test_settings
```

With a Visual Studio developer terminal:

```powershell
cl /nologo /std:c11 /O2 /W4 /I Firmware/Beta/tests/mocks /I Firmware/Beta/Inc Firmware/Beta/tests/test_firmware.c Firmware/Beta/Src/control_protocol.c Firmware/Beta/Src/settings.c /Fo:Firmware/build/ /Fe:Firmware/build/test_firmware.exe
Firmware/build/test_firmware.exe
```

The mocks verify transfer sizes, complete-frame gating, packet byte order, missed
events, timeouts, gain mapping, readback faults, RX bounds and malformed commands,
help topics/presets, settings commands, USB queue backpressure/batching, measured
rates, and IRQ wakeups without a SysTick delay. The settings simulation checks
no-op saves, torn/ECC/CRC recovery, full-journal behavior and factory reset.
Python tests check repeatable source generation, programming arguments and serial
reply handling. They cannot validate USB electrical behavior or ADC timing.

Before a hardware release: flash and verify a board, confirm repeated Windows
enumeration/unplug/replug, compare STATUS capture counts with measured DRDY and
received packet rates at all three settings, drive known signals into each ADC to
check framing/alignment/gain, stall a transport, and check recovery after reset.
