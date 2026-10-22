# Stacking boards: shared sampling clock and sync

**Sharing the ADC clock is hardware wiring. Aligning conversions also needs one
shared sync pulse after every board has been configured.** The current firmware
can use both with the connections below; it has no master/follower setting or
stack auto-detection. Every board still needs its own USB data connection.

These instructions describe the checked-in **FreeEEG32 beta / STM32H743ZI**
netlist and both PCB variants. Check component labels and continuity on your
actual revision before changing links. This stack wiring has not been bench-tested.

## Two different clocks

| Clock | What it does | Share across boards? |
| --- | --- | --- |
| **U8, 8.192 MHz** | Drives the four ADCs' MCLK inputs; sets the sampling timebase | **Yes: share this clock** |
| **Y2, 16 MHz** | STM32 processor crystal; feeds the selected CPU clock profile | Leave each board's Y2 in place |

All four ADCs on one board already share MCLK and SYNC_IN. The ADCs are
**AD7771BCPZ** in the BOM, although some schematic/driver names say AD7779.
The firmware assumes an **8.192 MHz** ADC input clock; do not substitute the MCU
clock or another frequency. No firmware rebuild or CPU-clock change is required
when replacing a follower's local 8.192 MHz source with the master's 8.192 MHz.

Sharing MCLK prevents relative sample-rate drift. Sharing SYNC_IN also aligns the
ADCs' digital filters. Neither identifies corresponding samples in separate USB
streams automatically; see [Data collection](#data-collection).

## Choose one master and prepare the links

The **master** supplies the ADC clock and sync pulse. Every other board is a
**follower**. Power off and disconnect USB before changing links or wiring.

| Connection | Master | Each follower |
| --- | --- | --- |
| **R117 / J73: U8 output to ADC MCLK** | Connected through R117 or a J73 shunt | **Open:** remove R117 if fitted and remove any J73 shunt |
| **R115 / J65: ADC1 SYNC_OUT to shared SYNC_IN** | Connected through R115 or a J65 shunt | **Open:** remove R115 if fitted and remove any J65 shunt |

R115 and R117 are **0-ohm resistors**, in parallel with the corresponding header
connections. Removing a shunt alone does not open the path if its resistor is
fitted. Check both with a continuity meter, before connecting the boards.
Opening follower R117 isolates its oscillator output; U8 can remain powered.
Opening follower R115 isolates its local sync output while allowing an external
pulse to reach all four ADCs.

Use only one clock driver and one sync driver on the shared nets. Do not connect
local oscillator outputs together or join multiple SYNC_OUT outputs. Leave the
MCU START pins separate; the firmware drives those pins as outputs.

## Connect these three signals

Use the **pin numbers**, not a left/right guess from a photograph. The square
pad identifies pin 1 on these two-pin headers; verify against the PCB/continuity.

| Signal | Master contact | Contact on every follower |
| --- | --- | --- |
| **ADC clock, 8.192 MHz** | **J89 pin 1** | **J89 pin 1** |
| **ADC sync** | **J90 pin 2** | **J90 pin 2** |
| **Board-side GND** | **J81 pin 1** | **J81 pin 1** |

The master MCLK reaches J89.1 through its R117/J73 link. Its ADC1 SYNC_OUT
reaches J90.2 through its R115/J65 link. The same contacts on followers feed
their four ADC inputs, with the local output drivers isolated as above.

**Do not bridge the two pins of J89 or J90.** J89 pin 2 is **VCM**, not ground;
J90 pin 1 is **GPIO0**, not ground. J81 pin 2 is a power rail. The table specifies
individual signal contacts, not instructions to stack every connector straight
through. Other headers carry reference voltages, supplies and GPIO signals;
verify their intended connections separately.

Keep clock/sync wiring short with a nearby ground return. Check clock amplitude,
edges and ringing at the furthest follower with an oscilloscope; larger stacks
may need a clock buffer. The passive fan-out limit has not been measured.
Keep existing USB/power isolation intact and use the board-side ground contact.

## Configure and synchronize

1. Flash every board individually with this fork's firmware. Label each board
   and record its USB serial number/COM port. The USB menu lets you choose a board
   when several are present.
2. With power disconnected, prepare the master/follower links and wire the three
   signals above. Power the master before followers so their ADC clock is present.
   Connect each board's USB data port to the computer.
3. Use **menu 6** on each board. Set the **same sample rate** on every board
   (512 Hz is the initial setting); set gains as needed. Choose Save if those
   settings should survive power-off, then **0: exit with streaming paused**.
   Close other EEG/serial software before opening configuration.
4. After **all followers** are configured, issue **`!RATE 512` on the master
   only**, even if it is already set to 512 Hz. Use the rate you selected in step 3.
   The existing RATE command reloads the master ADC settings and pulses START;
   master ADC1 generates the MCLK-synchronous pulse that now reaches every board.
   Allow at least **20 ms** for settling. Do not configure another board afterward
   without repeating this final master pulse.
5. Run **Check my board** on each board, while all are still paused. Then send
   **`!START` to each board** and open their USB streams in the recording software.
   START resumes capture without issuing another ADC synchronization pulse.

`!STOP` pauses transfer/capture; it does not stop the ADC sampling clock. There
is currently no `!SYNC` command. Reissuing RATE on the master is the available
way to generate the final shared synchronization pulse with this firmware.

### Direct commands: example with two boards at 512 Hz

Run menu 6 first so the USB helper environment is installed and both boards are
configured and paused. Replace **COM5** (master) and **COM6** (follower) with your
ports. Use the source checkout's root folder for these examples.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe Firmware\Beta\control.py --list
# Final shared sync, after configuring every board:
.\.venv\Scripts\python.exe Firmware\Beta\control.py --port COM5 "RATE 512" CHECK
.\.venv\Scripts\python.exe Firmware\Beta\control.py --port COM6 CHECK
# Resume both streams after checks pass:
.\.venv\Scripts\python.exe Firmware\Beta\control.py --port COM5 START
.\.venv\Scripts\python.exe Firmware\Beta\control.py --port COM6 START
```

Linux (example ports; confirm with `--list`):

```bash
.venv/bin/python Firmware/Beta/control.py --list
.venv/bin/python Firmware/Beta/control.py --port /dev/ttyACM0 "RATE 512" CHECK
.venv/bin/python Firmware/Beta/control.py --port /dev/ttyACM1 CHECK
.venv/bin/python Firmware/Beta/control.py --port /dev/ttyACM0 START
.venv/bin/python Firmware/Beta/control.py --port /dev/ttyACM1 START
```

The helper adds the `!` prefix; a plain serial terminal needs it. CHECK measures
DRDY for 500 ms and checks ADC settings. A passing check on each board does
**not** prove alignment between boards. A release ZIP has `control.py` in its
root; use that path instead of `Firmware/Beta/control.py` there.

## Data collection

- **One USB stream per board:** the current firmware does not combine a stack
  into one USB connection. Use host software that opens all board ports and
  assigns them consistent channel groups (1-32, 33-64, and so on).
- **First packets are not a common sample zero:** START commands and USB delivery
  occur at different times. The one-byte packet counters are local to each
  board; matching their values does not establish alignment across boards.
  A shared sample epoch/timestamp or a measured alignment marker is needed in
  host software for sample-by-sample merging. That coordination is not built in.
- **Verify the stack:** compare ADC1 DRDY edges between boards after the final
  sync, and record a known common test signal to check alignment and long-term
  drift. Individual recording tests check delivery, not cross-board phase.
- **Reconfigure as a group:** pause all boards before changing rate, loading
  settings, restoring defaults or rebooting/updating the master. Repeat the
  final master RATE pulse, settling and checks afterward, then re-establish host
  sample alignment. Master resets/rate changes send a sync to the whole stack.
  If the master loses power, followers lose their ADC clock; there is no
  automatic clock failover.

For independent 32-channel streams, boards can retain their own clocks and sync
links. That is a multi-board setup, but it will not provide a shared sampling
clock or guaranteed cross-board sample alignment.

## Circuit references

- [Beta netlist](../AssemblyFiles/KiCAD/FreeEEG32-beta.net),
  [beta PCB](../AssemblyFiles/KiCAD/FreeEEG32-beta.kicad_pcb) and
  [shorting-minuses PCB](../AssemblyFiles/KiCAD/FreeEEG32-beta-shorting-minuses.kicad_pcb):
  J73/R117, J65/R115, J89, J90 and J81 connections.
- [Oscillator schematic](../AssemblyFiles/KiCAD/CRYSTAL.sch): U8, BOM part CB3LV-3I-8M1920.
- [AD7771 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/AD7771.pdf),
  Clocking and Sampling / Digital Reset and Synchronization Pins, Figure 110:
  common MCLK and one SYNC_OUT driving multiple SYNC_IN inputs.
- Firmware: `Firmware/Beta/Src/runtime_stm32h743.c` (`runtime_adc_sync`) and
  `Firmware/Beta/Src/freeeeg32.c` (`set_rate`, `CONTROL_START`).
