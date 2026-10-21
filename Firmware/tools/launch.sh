#!/usr/bin/env bash
set -euo pipefail
task_tools="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="$(dirname -- "$task_tools")"; task_repo=0
if [[ -d "$task_root/Beta" ]]; then task_root="$(dirname -- "$task_root")"; task_repo=1; fi
task_action="${1:-menu}"; if (($#)); then shift; fi
task_cpu_mhz=80
if [[ "$task_action" == menu ]]; then
    printf '%s\n' 'FreeEEG32 beta' '1 Install/check all tools (Python, Arm compiler, OpenOCD, USB helper)' '2 Build UF2 from source' '3 Flash existing compiled firmware + UF2 loader with ST-Link' '4 Build edited source, then flash firmware + UF2 loader with ST-Link' '5 USB update' '6 Configure board (sample rate, gain, presets, saved settings)' '7 Check my board' '8 Test recording (10 seconds)' '9 Save a support report' '10 Back up settings to a file' '11 Restore settings from a file' '0 Exit'
    read -r -p 'Select: ' task_choice
    case "$task_choice" in 1) task_action=setup;; 2) task_action=build;; 3) task_action=flash;; 4) task_action=build-flash;; 5) task_action=usb-update;; 6) task_action=configure;; 7) task_action=check;; 8) task_action=record;; 9) task_action=report;; 10) task_action=backup;; 11) task_action=restore;; 0) exit 0;; *) exit 2;; esac
    if [[ "$task_action" == build || "$task_action" == build-flash ]]; then
        read -r -p 'Application CPU MHz: 40/80/160/240/320/400/480 [80]: ' task_cpu_mhz
        task_cpu_mhz="${task_cpu_mhz:-80}"
    fi
fi
if [[ "$task_action" == build || "$task_action" == build-flash ]]; then
    task_flash_args=()
    while (($#)); do
        case "$1" in
            --cpu-mhz)
                if (($# < 2)); then echo '--cpu-mhz needs a CPU profile (40/80/160/240/320/400/480).' >&2; exit 2; fi
                task_cpu_mhz="$2"; shift 2;;
            *) task_flash_args+=("$1"); shift;;
        esac
    done
    case "$task_cpu_mhz" in 40|80|160|240|320|400|480) ;; *) echo 'Choose CPU MHz: 40/80/160/240/320/400/480.' >&2; exit 2;; esac
    if [[ "$task_action" == build && ${#task_flash_args[@]} != 0 ]]; then echo 'Usage: build [--cpu-mhz 40|80|160|240|320|400|480]' >&2; exit 2; fi
    set -- "${task_flash_args[@]}"
fi
if [[ ( "$task_action" == build || "$task_action" == build-flash ) && "$task_repo" != 1 ]]; then
    echo 'Building requires the source repository, not only the precompiled release bundle.' >&2; exit 1
fi
case "$task_action" in
    setup|build|build-flash) bash "$task_tools/setup-linux.sh";;
    flash) bash "$task_tools/setup-linux.sh" --flash-only;;
    usb-update|configure|check|record|report|backup|restore) bash "$task_tools/setup-linux.sh" --serial-only;;
    *) echo 'Usage: bash FreeEEG32.sh [setup|build|flash|build-flash|usb-update|configure|check|record|report|backup|restore] [arguments]' >&2; exit 2;;
esac
task_python="$task_root/.venv/bin/python"
if [[ "$task_action" == setup ]]; then exit 0; fi
if [[ "$task_action" == build || "$task_action" == build-flash ]]; then
    if [[ "$task_repo" != 1 ]]; then echo 'Building requires the source repository.' >&2; exit 1; fi
    "$task_python" "$task_root/Firmware/UF2/build.py" --cpu-mhz "$task_cpu_mhz"
fi
if [[ "$task_repo" == 1 ]]; then task_flash="$task_root/Firmware/Beta/flash.py"; task_device="$task_root/Firmware/Beta/device.py";
else task_flash="$task_root/flash.py"; task_device="$task_root/device.py"; fi
if [[ "$task_action" == flash || "$task_action" == build-flash ]]; then "$task_python" "$task_flash" "$@"; fi
if [[ "$task_action" == usb-update ]]; then
    # Retain the former positional port/drive/image arguments as overrides.
    task_device_args=()
    if (($#)) && [[ "$1" != --* ]]; then
        if [[ -n "$1" ]]; then task_device_args+=(--port "$1"); fi; shift
        if (($#)) && [[ "$1" != --* ]]; then
            if [[ -n "$1" ]]; then task_device_args+=(--drive "$1"); fi; shift
        fi
        if (($#)) && [[ "$1" != --* ]]; then task_device_args+=(--image "$1"); shift; fi
    fi
    if [[ "$task_repo" == 1 ]]; then task_image="$task_root/Firmware/build/uf2/freeeeg32-application.uf2";
    else task_image="$task_root/freeeeg32-application.uf2"; fi
    if [[ "$task_repo" == 1 && ! -f "$task_image" && -f "$task_root/Precompiled/freeeeg32-application.uf2" ]]; then
        task_image="$task_root/Precompiled/freeeeg32-application.uf2"
    fi
    "$task_python" -u "$task_device" update --image "$task_image" "${task_device_args[@]}" "$@"
fi
case "$task_action" in
    configure|check|record|report|backup|restore) "$task_python" -u "$task_device" "$task_action" "$@";;
esac
