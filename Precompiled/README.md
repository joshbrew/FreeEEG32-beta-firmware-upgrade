# Ready-to-flash firmware (80 MHz)

- **[Complete release ZIP](freeeeg32-uf2-release.zip)**: download and extract it, then run `FreeEEG32.cmd` on Windows or `bash FreeEEG32.sh` on Linux.
- **[Factory HEX](freeeeg32-factory.hex)**: EEG firmware + UF2 bootloader for first installation/recovery with ST-Link (menu **3**).
- **[Application UF2](freeeeg32-application.uf2)**: USB update for a board with the loader installed (menu **5**, or double-reset and copy to FREEEEG32).
- **[Build manifest](manifest.json)** and **[checksums](SHA256SUMS.txt)** identify the compiled firmware.

These files are tracked in Git. A local default 80 MHz build refreshes them, so
include the updated `Precompiled/` files when committing a firmware change.
After pushes to `master`, GitHub Actions tests all seven clock profiles and the
Windows/Linux helpers, then commits the verified default 80 MHz downloads here
and updates the [rolling beta release](https://github.com/joshbrew/FreeEEG32-beta-firmware-upgrade/releases/tag/latest-beta).
Run `git pull --ff-only` before your next push to pick up that generated commit.
On a fresh clone, menu **3** automatically uses this folder's factory HEX; menu
**5** uses its UF2. If a local build exists, those actions prefer that build.
Other clock profiles remain available in the workflow's build artifacts.

If checks fail, the previous automatic downloads remain available. Updating this
folder manually does not run the checks. Images remain beta until physical-board
validation is complete. See the [main guide](../README.md) for wiring and setup.
