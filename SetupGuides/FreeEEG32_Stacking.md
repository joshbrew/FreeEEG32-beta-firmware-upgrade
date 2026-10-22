# Stack boards using one clock

Use **one master** board and make the others **followers**. Flash the same firmware
onto every board. **No firmware clock setting needs changing.** Share the ADC's
**8.192 MHz clock (U8)**; leave each processor's **Y2 crystal** alone.

The wiring below also shares a sync pulse so the ADCs convert together. It is
checked against the board files, but **has not been tested on a physical stack**.

## 1. Prepare the boards with all power disconnected

| Link | Master | Every follower |
| --- | --- | --- |
| **R117 / J73 — clock** | Keep connected | Remove **R117** if fitted and any **J73** shunt |
| **R115 / J65 — sync** | Keep connected | Remove **R115** if fitted and any **J65** shunt |

R115 and R117 are **0-ohm resistors**. Each is wired across the same connection
as its header shunt: **removing just the shunt may leave the connection closed**.
Check continuity. Followers must not drive their own clock or sync onto the shared wires.

## 2. Connect these three wires

Connect the master to **every follower** using these contacts:

| Signal | Master | Each follower |
| --- | --- | --- |
| **Clock** | **J89 pin 1** | **J89 pin 1** |
| **Sync** | **J90 pin 2** | **J90 pin 2** |
| **GND** | **J81 pin 1** | **J81 pin 1** |

Use pin numbers and verify your board revision. On these headers, pin 1 is the
square pad. **Connect only the contacts listed:** J89 pin 2 is VCM, J90 pin 1 is
GPIO0, and J81 pin 2 is power. Do not short the two pins together or assume every
stacking header can be connected straight through. Keep wires short with a nearby
ground return; larger stacks may need a clock buffer.

## 3. Configure and start

1. **Power the master first**, then the followers. Connect **each board's USB
   data port** to the computer. Label the boards and note their COM/serial ports.
2. Open **menu 6** for each board. Select the **same sample rate** on every board
   (start with **512 Hz**), set gains, and save if wanted. Choose **0** to leave
   each board paused. Close EEG software while using the menus.
3. After configuring **all boards**, send **RATE 512 to the master only**, even
   if it already uses 512 Hz. This sends the shared sync pulse. Use your chosen
   rate if different. The commands below also run CHECK, allowing time to settle.
4. Run **menu 7** on each follower to check it. If checks pass, use **menu 6 → 8**
   on each board to start streaming. Do not change settings between sync and start.

For step 3, run this from the repository folder. Replace the example port with
the **master's** port. Menu 6 installs the helper environment first.

**Windows PowerShell:**

```powershell
.\.venv\Scripts\python.exe Firmware\Beta\control.py --port COM5 "RATE 512" CHECK
```

**Linux:**

```bash
.venv/bin/python Firmware/Beta/control.py --port /dev/ttyACM0 "RATE 512" CHECK
```

In an extracted release ZIP, use `control.py` instead of `Firmware/Beta/control.py`.
In a plain serial terminal, send `!RATE 512` followed by a newline, wait at least
20 ms, then send `!CHECK`. There is no separate SYNC command.

## Keep in mind

- **Each board still has its own USB stream.** Recording software must open all
  ports and align their samples. Matching packet-counter values or first-arriving
  USB packets does not establish alignment between boards.
- Pause all boards and repeat step 3 after changing settings or rebooting a board.
  Stop the stack before updating or powering off the master: followers depend on
  its clock. There is no automatic replacement clock.
- Check cross-board DRDY timing and a common test signal before relying on sample
  alignment. Menu 7 and the recording test check individual boards, not the stack's
  alignment or the clock wiring's signal quality.

Pinout sources: [netlist](../AssemblyFiles/KiCAD/FreeEEG32-beta.net),
[PCB](../AssemblyFiles/KiCAD/FreeEEG32-beta.kicad_pcb),
[second PCB variant](../AssemblyFiles/KiCAD/FreeEEG32-beta-shorting-minuses.kicad_pcb).
The [AD7771 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/AD7771.pdf),
Figure 110, describes shared MCLK and one SYNC_OUT driving multiple SYNC_IN inputs.
