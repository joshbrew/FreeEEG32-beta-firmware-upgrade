#include "freeeeg32.h"
#include "control_protocol.h"
#include "main.h"
#include "ad7779.h"
#include "usbd_cdc_if.h"
#include "settings.h"
#include "runtime.h"
#include "clock_profile.h"
#include "firmware_identity.h"
#include "watchdog.h"
#include <stdio.h>
#include <string.h>
#ifdef FREEEEG32_UF2_APPLICATION
#include "boot_request.h"
#endif

extern SAI_HandleTypeDef hsai_BlockB2, hsai_BlockA1, hsai_BlockB1, hsai_BlockA2;
extern UART_HandleTypeDef huart1;
extern ad7779_dev *devices[4];
static SAI_HandleTypeDef *const sais[] = { &hsai_BlockB2, &hsai_BlockA1, &hsai_BlockB1, &hsai_BlockA2 };
/* DMA1/2 cannot access DTCM. D-cache remains disabled, as in the base firmware. */
DMA_BUFFER static uint32_t samples[4][8] __attribute__((aligned(32)));
DMA_BUFFER static uint8_t uart_frame[105] __attribute__((aligned(32)));
static uint8_t frame[105];
static volatile uint32_t ready_events, rx_write, rx_read, rx_dropped;
static uint8_t rx[512];
static uint32_t seen_events, acquired, missed, dma_errors, usb_dropped, uart_dropped;
static uint32_t capture_started, sequence, rate = 512, settle_until;
static eeg_settings current_settings;
static int settings_dirty, settings_from_flash;
#define USB_QUEUE_FRAMES 16u
static uint8_t usb_queue[USB_QUEUE_FRAMES][105];
static uint32_t usb_head, usb_tail, usb_high_water, control_discarded;
static volatile uint32_t drdy_stamp;
static uint32_t capture_stamp, max_capture_us, max_latency_us, max_work_us, reset_flags;
static uint32_t window_stamp, window_events, window_acquired, window_wait_us;
static uint32_t measured_drdy_millihz, measured_capture_millihz, measured_wait_permille, measured_window_us;
static uint32_t sleep_entries;
static int capturing, streaming = 1, start_after_reply, reboot_after_reply, adc_fault;
static uint32_t adc_fault_mask, last_fault_adc, last_fault_reg, last_fault_value;
#ifndef FREEEEG32_STRICT_READBACK
#define FREEEEG32_STRICT_READBACK 0
#endif
static uint32_t readback_mask; /* ADCs whose register readback disagreed with a write. */static const char *last_fault_op = "NONE";
#ifdef FREEEEG32_UF2_APPLICATION
static int bootloader_after_reply;
#endif
static control_parser parser;
static char reply[512];
static uint16_t reply_length;
static int reply_in_flight;
static uint32_t last_rx_dropped;

void FreeEEG32_DataReady(uint16_t pin)
{
    if (pin == ADC1_DRDY_Pin) { drdy_stamp = runtime_micros(); ++ready_events; }
}

void FreeEEG32_Receive(const uint8_t *data, uint32_t length)
{
    uint32_t i;
    for (i = 0; i < length; ++i) {
        if (rx_write - rx_read == sizeof(rx)) { ++rx_dropped; continue; }
        rx[rx_write % sizeof(rx)] = data[i];
        __DMB();
        ++rx_write;
    }
}

static void stop_capture(void)
{
    unsigned i;
    for (i = 0; i < 4; ++i) HAL_SAI_DMAStop(sais[i]);
    capturing = 0;
    seen_events = ready_events;
}

/* Always read back the hardware registers: cached values alone cannot verify SPI. */
static void adc_problem(unsigned adc, uint8_t reg, const char *operation)
{
    adc_fault = 1; adc_fault_mask |= 1u << adc;
    last_fault_adc = adc + 1; last_fault_reg = reg; last_fault_op = operation;
}

/* 1 = matches; 0 = read succeeded but disagrees; -1 = SPI read failed. */
static int readback(ad7779_dev *dev, uint8_t reg, uint8_t expected, uint8_t mask)
{
    uint8_t actual = 0;
    unsigned i;
    int read_ok = ad7779_spi_int_reg_read(dev, reg, &actual) == 0;
    int match = read_ok && (actual & mask) == (expected & mask);
    if (!match) for (i = 0; i < 4; ++i) if (devices[i] == dev) {
        if (read_ok && !FREEEEG32_STRICT_READBACK) {
            readback_mask |= 1u << i;
            last_fault_adc = i + 1; last_fault_reg = reg; last_fault_op = "READBACK";
            last_fault_value = actual;
        } else adc_problem(i, reg, "READBACK");
    }
    return match ? 1 : read_ok ? 0 : -1;
}

/* A mismatch is reported in readback_mask. Only SPI errors stop acquisition, unless
   built with FREEEEG32_STRICT_READBACK=1. !CHECK always reports the true readback. */
static int verify(ad7779_dev *dev, uint8_t reg, uint8_t expected, uint8_t mask)
{
    int result = readback(dev, reg, expected, mask);
    return result > 0 || (result == 0 && !FREEEEG32_STRICT_READBACK);
}

/* The ADCs are AD7771 (BOM: AD7771BCPZ). Its SINC5 filter limits the decimation to
   16..2048, i.e. at least 1 kHz from the 2.048 MHz high-resolution modulator, so 512 Hz
   needs the SINC3 filter (16..4095.99). The base initialization selects SINC5 with a raw
   SPI write, which the driver cache does not see, so read the live register here. */
static int select_sinc3(void)
{
    unsigned i;
    int ok = 1;
    for (i = 0; i < 4; ++i) {
        uint8_t value = 0;
        if (ad7779_spi_int_reg_read(devices[i], AD7779_REG_GENERAL_USER_CONFIG_2, &value) != 0 ||
            ((value & AD7771_FILTER_MODE) &&
             ad7779_spi_int_reg_write(devices[i], AD7779_REG_GENERAL_USER_CONFIG_2,
                                      (uint8_t)(value & ~AD7771_FILTER_MODE)) != 0)) {
            adc_problem(i, AD7779_REG_GENERAL_USER_CONFIG_2, "FILTER"); ok = 0;
        }
    }
    /* A filter change takes effect cleanly only after a synchronization. */
    runtime_adc_sync();
    return ok;
}

/* DRDY rate over 500 ms; DRDY keeps counting while streaming is paused. */
static uint32_t measure_drdy_hz(void)
{
    uint32_t before = ready_events;
    HAL_Delay(500);
    return (ready_events - before) * 2u;
}

static int set_rate(uint32_t hz)
{
    unsigned i;
    /* BOM oscillator 8.192 MHz; HR modulator clock MCLK / 4 = 2.048 MHz. */
    uint16_t decimation = (uint16_t)(2048000u / hz);
    int ok = 1;
    stop_capture();
    for (i = 0; i < 4; ++i) {
        ad7779_dev *dev = devices[i];
        if (ad7779_set_dec_rate(dev, decimation, 0) != 0) {
            adc_problem(i, AD7779_REG_SRC_N_MSB, "RATE_WRITE"); ok = 0;
        }
        if (!verify(dev, AD7779_REG_SRC_N_MSB, (uint8_t)(decimation >> 8), 15) ||
            !verify(dev, AD7779_REG_SRC_N_LSB, (uint8_t)decimation, 255) ||
            !verify(dev, AD7779_REG_SRC_IF_MSB, 0, 255) ||
            !verify(dev, AD7779_REG_SRC_IF_LSB, 0, 255)) ok = 0;
    }
    /* Load all four SRC values using the base firmware's software update sequence. */
    for (i = 0; i < 4; ++i) {
        if (ad7779_spi_int_reg_write_mask(devices[i], AD7779_REG_SRC_UPDATE,
                AD7779_SRC_LOAD_SOURCE | AD7779_SRC_LOAD_UPDATE, AD7779_SRC_LOAD_UPDATE) != 0) {
            adc_problem(i, AD7779_REG_SRC_UPDATE, "RATE_LOAD"); ok = 0;
        }
    }
    HAL_Delay(1);
    for (i = 0; i < 4; ++i)
        if (ad7779_spi_int_reg_write_mask(devices[i], AD7779_REG_SRC_UPDATE,
                AD7779_SRC_LOAD_UPDATE, 0) != 0) {
            adc_problem(i, AD7779_REG_SRC_UPDATE, "RATE_LOAD"); ok = 0;
        }
    /* Sequential SPI loads leave the four ADCs offset; a START pulse resynchronizes
       their digital filters so all 32 channels sample together. Discard settling data. */
    runtime_adc_sync();
    settle_until = HAL_GetTick() + 20;
    if (ok) { rate = hz; current_settings.rate = hz; }
    if (!ok) adc_fault = 1;
    return ok;
}

static int set_gain(unsigned channel, unsigned value)
{
    unsigned gain = value == 8 ? 3 : value == 4 ? 2 : value == 2 ? 1 : 0;
    ad7779_dev *dev = devices[channel / 8];
    int ok = ad7779_set_gain(dev, (ad7779_ch)(channel % 8), (ad7779_gain)gain) == 0;
    if (!ok) adc_problem(channel / 8, AD7779_REG_CH_CONFIG(channel % 8), "GAIN_WRITE");
    if (!verify(dev, AD7779_REG_CH_CONFIG(channel % 8), (uint8_t)(gain << 6), 0xc0)) ok = 0;
    if (ok) current_settings.gains[channel] = (uint8_t)value;
    else adc_fault = 1;
    settle_until = HAL_GetTick() + 20;
    return ok;
}

static int apply_settings(const eeg_settings *settings)
{
    eeg_settings copy = *settings;
    unsigned ch;
    int ok = set_rate(copy.rate);
    for (ch = 0; ch < 32; ++ch) if (!set_gain(ch, copy.gains[ch])) ok = 0;
    return ok;
}

static void diagnostics_update(void)
{
    uint32_t now = runtime_micros(), elapsed = now - window_stamp;
    if (!streaming || (int32_t)(HAL_GetTick() - settle_until) < 0) {
        window_stamp = now; window_events = ready_events; window_acquired = acquired; window_wait_us = 0;
        return;
    }
    if (elapsed < 1000000u) return;
    measured_drdy_millihz = (uint32_t)((uint64_t)(ready_events - window_events) * 1000000000u / elapsed);
    measured_capture_millihz = (uint32_t)((uint64_t)(acquired - window_acquired) * 1000000000u / elapsed);
    measured_wait_permille = (uint32_t)((uint64_t)window_wait_us * 1000u / elapsed);
    measured_window_us = elapsed;
    window_stamp = now; window_events = ready_events; window_acquired = acquired; window_wait_us = 0;
}

static void command(control_command cmd)
{
    int ok, was_streaming = streaming;
    diagnostics_update();
    streaming = 0; /* Every control transaction enters a quiet configuration mode. */
    start_after_reply = 0;
    if (capturing) ++control_discarded;
    stop_capture();
    switch (cmd.kind) {
    case CONTROL_HELP:
        if (cmd.first == 1) snprintf(reply, sizeof(reply), "OK HELP SETTINGS !SETTINGS shows all gains/rate; !SAVE persists current settings; !LOAD restores saved settings; !FACTORY erases saved settings and restores 512Hz/gain8; config pauses streaming, !START resumes\r\n");
        else if (cmd.first == 2) snprintf(reply, sizeof(reply), "OK HELP PRESETS !PRESET DEFAULT=512Hz/gain8 FAST=2048Hz/gain8 LOWGAIN=1024Hz/gain1; applies all 32 channels, pauses streaming, does not save; !SAVE persists, !START resumes\r\n");
        else if (cmd.first == 3) snprintf(reply, sizeof(reply), "OK HELP DIAG last full streaming window: drdy_millihz and capture_millihz (divide by 1000 for Hz), max_capture_us, max_latency_us, max_work_us, wait_permille (WFI wait fraction, not CPU utilization), reset_flags hex; !STATUS shows drops; !START resumes\r\n");
        else snprintf(reply, sizeof(reply), "OK HELP !INFO !STATUS !DIAG !CHECK !SETTINGS !STOP !START !RATE 512|1024|2048 !GAIN channel(1..32) 1|2|4|8 !PRESET DEFAULT|FAST|LOWGAIN !SAVE !LOAD !FACTORY !REBOOT !BOOTLOADER; controls pause stream, !START resumes; !HELP SETTINGS|PRESETS|DIAG\r\n");
        break;
    case CONTROL_INFO:
#ifdef FREEEEG32_UF2_APPLICATION
        snprintf(reply, sizeof(reply), "OK INFO FreeEEG32-beta " FREEEEG32_VERSION " STM32H743 32ch CDC protocol=1 update=UF2 settings=flash-explicit-save idle=" FREEEEG32_IDLE_NAME " usb_queue=16 cpu_mhz=%lu ahb_mhz=%lu requested_mhz=%u silicon_rev=0x%04lx build=%s watchdog=%s watchdog_nominal_ms=32768 clock=%s\r\n",
            (unsigned long)(SystemCoreClock / 1000000u), (unsigned long)(HAL_RCC_GetHCLKFreq() / 1000000u),
            (unsigned)FREEEEG32_CPU_MHZ, (unsigned long)HAL_GetREVID(), FREEEEG32_BUILD_TAG, watchdog_active() ? "IWDG1" : "not-started", runtime_clock_source());
#else
        snprintf(reply, sizeof(reply), "OK INFO FreeEEG32-beta " FREEEEG32_VERSION " STM32H743 32ch CDC protocol=1 update=SWD settings=flash-explicit-save idle=" FREEEEG32_IDLE_NAME " usb_queue=16 cpu_mhz=%lu ahb_mhz=%lu requested_mhz=%u silicon_rev=0x%04lx build=%s watchdog=%s watchdog_nominal_ms=32768 clock=%s\r\n",
            (unsigned long)(SystemCoreClock / 1000000u), (unsigned long)(HAL_RCC_GetHCLKFreq() / 1000000u),
            (unsigned)FREEEEG32_CPU_MHZ, (unsigned long)HAL_GetREVID(), FREEEEG32_BUILD_TAG, watchdog_active() ? "IWDG1" : "not-started", runtime_clock_source());
#endif
        break;
    case CONTROL_STATUS:
        snprintf(reply, sizeof(reply), "OK STATUS rate=%lu acquired=%lu missed=%lu dma_errors=%lu usb_dropped=%lu uart_dropped=%lu rx_dropped=%lu adc_fault=%d streaming=0 usb_queued=%lu usb_high_water=%lu control_discarded=%lu adc_fault_mask=0x%lx last_adc=%lu last_reg=0x%02lx last_op=%s uptime_ms=%lu readback_mask=0x%lx\r\n",
            (unsigned long)rate, (unsigned long)acquired, (unsigned long)missed,
            (unsigned long)dma_errors, (unsigned long)usb_dropped, (unsigned long)uart_dropped,
            (unsigned long)rx_dropped, adc_fault, (unsigned long)(usb_head - usb_tail),
            (unsigned long)usb_high_water, (unsigned long)control_discarded, (unsigned long)adc_fault_mask,
            (unsigned long)last_fault_adc, (unsigned long)last_fault_reg, last_fault_op, (unsigned long)HAL_GetTick(),
            (unsigned long)readback_mask); break;
    case CONTROL_CHECK: {
        unsigned i, ch;
        uint32_t failed = 0, decimation = 2048000u / rate, drdy_hz = measure_drdy_hz();
        /* All four ADCs share MCLK and SYNC; ADC1's DRDY clocks every capture. */
        int rate_ok = drdy_hz * 100u >= rate * 99u && drdy_hz * 100u <= rate * 101u;
        for (i = 0; i < 4; ++i) {
            int good = rate_ok;
            if (readback(devices[i], AD7779_REG_SRC_N_MSB, (uint8_t)(decimation >> 8), 15) <= 0) good = 0;
            if (readback(devices[i], AD7779_REG_SRC_N_LSB, (uint8_t)decimation, 255) <= 0) good = 0;
            if (readback(devices[i], AD7779_REG_SRC_IF_MSB, 0, 255) <= 0) good = 0;
            if (readback(devices[i], AD7779_REG_SRC_IF_LSB, 0, 255) <= 0) good = 0;
            if (readback(devices[i], AD7779_REG_GENERAL_USER_CONFIG_2, 0, AD7771_FILTER_MODE) <= 0) good = 0;
            for (ch = 0; ch < 8; ++ch) {
                unsigned gain = current_settings.gains[i * 8 + ch];
                unsigned code = gain == 8 ? 3 : gain == 4 ? 2 : gain == 2 ? 1 : 0;
                if (readback(devices[i], AD7779_REG_CH_CONFIG(ch), (uint8_t)(code << 6), 0xc0) <= 0) good = 0;
            }
            if (!good) failed |= 1u << i;
        }
        snprintf(reply, sizeof(reply), "OK CHECK adc_ok_mask=0x%lx adc_failed_mask=0x%lx adc_fault=%d last_adc=%lu last_reg=0x%02lx last_op=%s readback_mask=0x%lx drdy_hz=%lu rate_ok=%d last_value=0x%02lx\r\n",
            (unsigned long)(15u & ~failed), (unsigned long)failed, adc_fault,
            (unsigned long)last_fault_adc, (unsigned long)last_fault_reg, last_fault_op,
            (unsigned long)readback_mask, (unsigned long)drdy_hz, rate_ok, (unsigned long)last_fault_value);
        break;
    }
    case CONTROL_DIAG:
        snprintf(reply, sizeof(reply), "OK DIAG drdy_millihz=%lu capture_millihz=%lu window_us=%lu max_capture_us=%lu max_latency_us=%lu max_work_us=%lu wait_permille=%lu sleep_entries=%lu reset_flags=0x%08lx\r\n",
            (unsigned long)measured_drdy_millihz, (unsigned long)measured_capture_millihz,
            (unsigned long)measured_window_us, (unsigned long)max_capture_us, (unsigned long)max_latency_us,
            (unsigned long)max_work_us, (unsigned long)measured_wait_permille,
            (unsigned long)sleep_entries, (unsigned long)reset_flags); break;
    case CONTROL_SETTINGS: {
        unsigned ch, used = (unsigned)snprintf(reply, sizeof(reply), "OK SETTINGS rate=%lu source=%s dirty=%d gains=",
            (unsigned long)rate, settings_from_flash ? "saved" : "defaults", settings_dirty);
        for (ch = 0; ch < 32; ++ch) used += (unsigned)snprintf(reply + used, sizeof(reply) - used,
            "%s%u", ch ? "," : "", current_settings.gains[ch]);
        snprintf(reply + used, sizeof(reply) - used, "\r\n"); break;
    }
    case CONTROL_SAVE:
        ok = adc_fault ? 0 : settings_save(&current_settings);
        if (ok == 1) { settings_from_flash = 1; settings_dirty = 0; snprintf(reply, sizeof(reply), "OK SAVE\r\n"); }
        else snprintf(reply, sizeof(reply), ok == -1 ? "ERR SAVE journal full; FACTORY recycles it\r\n" : "ERR SAVE ADC fault or flash failure\r\n");
        break;
    case CONTROL_LOAD: {
        eeg_settings saved;
        int found = settings_load(&saved);
        ok = apply_settings(&saved);
        if (ok) { settings_from_flash = found; settings_dirty = 0; }
        snprintf(reply, sizeof(reply), ok ? "OK LOAD source=%s\r\n" : "ERR LOAD SPI/readback; reboot before START\r\n", found ? "saved" : "defaults");
        break;
    }
    case CONTROL_FACTORY: {
        eeg_settings defaults;
        settings_defaults(&defaults);
        ok = apply_settings(&defaults) && !adc_fault && settings_factory();
        if (ok) { settings_from_flash = 1; settings_dirty = 0; }
        else settings_dirty = 1;
        snprintf(reply, sizeof(reply), ok ? "OK FACTORY 512Hz gain8 saved\r\n" : "ERR FACTORY ADC/flash failure; stream stopped\r\n");
        break;
    }
    case CONTROL_PRESET: {
        eeg_settings preset;
        settings_defaults(&preset);
        if (cmd.first == 2) preset.rate = 2048;
        if (cmd.first == 3) { preset.rate = 1024; memset(preset.gains, 1, 32); }
        ok = apply_settings(&preset); settings_dirty = 1;
        snprintf(reply, sizeof(reply), ok ? "OK PRESET %s unsaved\r\n" : "ERR PRESET SPI/readback; reboot before START\r\n",
            cmd.first == 2 ? "FAST" : cmd.first == 3 ? "LOWGAIN" : "DEFAULT");
        break;
    }
    case CONTROL_STOP:
        snprintf(reply, sizeof(reply), "OK STOP was_streaming=%d\r\n", was_streaming); break;
    case CONTROL_START:
        if (adc_fault) snprintf(reply, sizeof(reply), "ERR ADC configuration; reboot before START\r\n");
        else { snprintf(reply, sizeof(reply), "OK START\r\n"); start_after_reply = 1; }
        break;
    case CONTROL_RATE:
        ok = set_rate(cmd.first);
        settings_dirty = 1;
        snprintf(reply, sizeof(reply), ok ? "OK RATE %lu\r\n" : "ERR RATE SPI/readback; stream stopped\r\n", (unsigned long)rate);
        break;
    case CONTROL_GAIN: {
        ok = set_gain(cmd.first - 1, cmd.second); settings_dirty = 1;
        snprintf(reply, sizeof(reply), ok ? "OK GAIN %lu %lu\r\n" : "ERR GAIN SPI/readback; stream stopped\r\n",
                 (unsigned long)cmd.first, (unsigned long)cmd.second);
        break;
    }
    case CONTROL_SPIREAD: {
        /* Raw read frames for one register: 2-byte, 2-byte again (shows a reply that arrives
           one frame late), then 3-byte. Every received byte is reported. */
        uint8_t tx[3] = { (uint8_t)(0x80u | cmd.second), 0, 0 }, a[3] = {0}, b[3] = {0}, c[3] = {0};
        unsigned adc = cmd.first - 1;
        int ra = runtime_adc_spi_raw(adc, tx, a, 2);
        int rb = runtime_adc_spi_raw(adc, tx, b, 2);
        int rc = runtime_adc_spi_raw(adc, tx, c, 3);
        uint8_t driver_value = 0;
        int rd = ad7779_spi_int_reg_read(devices[adc], (uint8_t)cmd.second, &driver_value);
        snprintf(reply, sizeof(reply), "OK SPIREAD adc=%lu reg=0x%02lx f1=%02x,%02x f2=%02x,%02x f3=%02x,%02x,%02x status=%d,%d,%d driver=%02x,%d\r\n",
            (unsigned long)cmd.first, (unsigned long)cmd.second, a[0], a[1], b[0], b[1], c[0], c[1], c[2], ra, rb, rc,
            driver_value, rd);
        break;
    }
    case CONTROL_SPIWRITE: {
        /* Raw write for bench diagnosis; bypasses settings, verification and caches. */
        uint8_t tx[2] = { (uint8_t)(cmd.second & 0x7fu), (uint8_t)cmd.third }, rx[2] = {0};
        int status = runtime_adc_spi_raw(cmd.first - 1, tx, rx, 2);
        snprintf(reply, sizeof(reply), "OK SPIWRITE adc=%lu reg=0x%02lx value=0x%02lx rx=%02x,%02x status=%d\r\n",
            (unsigned long)cmd.first, (unsigned long)cmd.second, (unsigned long)cmd.third, rx[0], rx[1], status);
        break;
    }
    case CONTROL_REBOOT:
        snprintf(reply, sizeof(reply), "OK REBOOT\r\n"); reboot_after_reply = 1; break;
    case CONTROL_BOOTLOADER:
#ifdef FREEEEG32_UF2_APPLICATION
        snprintf(reply, sizeof(reply), "OK BOOTLOADER\r\n"); bootloader_after_reply = 1;
#else
        snprintf(reply, sizeof(reply), "ERR install the UF2 factory image with SWD first\r\n");
#endif
        break;
    default:
        snprintf(reply, sizeof(reply), "ERR command; use !HELP\r\n"); break;
    }
    reply_length = (uint16_t)strlen(reply);
}

static void send_frame(void)
{
    unsigned adc, ch;
    frame[0] = 0xa0; frame[1] = (uint8_t)sequence++;
    for (adc = 0; adc < 4; ++adc) for (ch = 0; ch < 8; ++ch) {
        uint32_t value = samples[adc][ch];
        unsigned index = 2 + adc * 24 + ch * 3;
        frame[index] = (uint8_t)(value >> 16);
        frame[index + 1] = (uint8_t)(value >> 8);
        frame[index + 2] = (uint8_t)value;
    }
    memset(frame + 98, 0, 6); frame[104] = 0xc0;
    /* Queue complete frames without waiting for USB. Preserve the byte-stream
       framing; batching changes USB transfer boundaries, not EEG packets. */
    if (usb_head - usb_tail == USB_QUEUE_FRAMES) ++usb_dropped;
    else {
        memcpy(usb_queue[usb_head % USB_QUEUE_FRAMES], frame, sizeof(frame)); ++usb_head;
        if (usb_head - usb_tail > usb_high_water) usb_high_water = usb_head - usb_tail;
    }
    if (HAL_UART_GetState(&huart1) == HAL_UART_STATE_READY) {
        memcpy(uart_frame, frame, sizeof(frame));
        if (HAL_UART_Transmit_DMA(&huart1, uart_frame, sizeof(frame)) != HAL_OK) ++uart_dropped;
    } else ++uart_dropped;
}

static void pump_usb(void)
{
    uint32_t frames = usb_head - usb_tail, index = usb_tail % USB_QUEUE_FRAMES;
    if (frames > USB_QUEUE_FRAMES - index) frames = USB_QUEUE_FRAMES - index;
    /* Up to 1680 bytes, below CDC's owned 2048-byte TX buffer. A busy endpoint
       retains the queue. No sample-rate throttling or per-frame delay. */
    if (frames && CDC_Transmit_HS(usb_queue[index], (uint16_t)(frames * sizeof(frame))) == USBD_OK)
        usb_tail += frames;
}

static void acquire(void)
{
    unsigned i;
    uint32_t events, stamp, now, primask;
    if (capturing) {
        int complete = 1;
        for (i = 0; i < 4; ++i) if (HAL_SAI_GetState(sais[i]) != HAL_SAI_STATE_READY) complete = 0;
        if (complete) {
            int error = 0;
            uint32_t elapsed = runtime_micros() - capture_stamp;
            if (elapsed > max_capture_us) max_capture_us = elapsed;
            __DMB();
            capturing = 0;
            for (i = 0; i < 4; ++i) {
                if (HAL_SAI_GetError(sais[i]) & ~(uint32_t)(HAL_SAI_ERROR_AFSDET | HAL_SAI_ERROR_LFSDET)) error = 1;
                /* Normal DMA completion leaves SAI enabled. Stop and flush its FIFO
                   before the next DRDY so old words cannot become the next frame. */
                if (HAL_SAI_DMAStop(sais[i]) != HAL_OK) error = 1;
            }
            if (error) ++dma_errors;
            else { ++acquired; send_frame(); }
        } else if (HAL_GetTick() - capture_started >= 10) {
            ++dma_errors; stop_capture();
        }
        return;
    }
    primask = __get_PRIMASK();
    __disable_irq();
    events = ready_events; stamp = drdy_stamp; now = runtime_micros();
    __set_PRIMASK(primask);
    if (events == seen_events) return;
    if (events - seen_events > 1) missed += events - seen_events - 1;
    seen_events = events;
    capture_stamp = now;
    if (now - stamp > max_latency_us) max_latency_us = now - stamp;
    capture_started = HAL_GetTick(); capturing = 1;
    for (i = 0; i < 4; ++i) {
        int started;
        primask = __get_PRIMASK();
        __disable_irq();
        /* Count words, never SAI_DATASIZE_32 (which is a register bitmask = 224). */
        started = HAL_SAI_Receive_DMA(sais[i], (uint8_t *)samples[i], 8);
        /* Slave RX DMA enables frame-sync error IRQs, and the HAL aborts the DMA on them.
           DCLK runs between DRDY frames, so FS is always "late" for a 256-bit frame. */
        __HAL_SAI_DISABLE_IT(sais[i], SAI_IT_AFSDET | SAI_IT_LFSDET);
        __HAL_SAI_CLEAR_FLAG(sais[i], SAI_FLAG_AFSDET | SAI_FLAG_LFSDET);
        __set_PRIMASK(primask);
        if (started != HAL_OK) {
            ++dma_errors; stop_capture(); break;
        }
    }
}

static int usb_ready(void)
{
    extern USBD_HandleTypeDef hUsbDeviceHS;
    USBD_CDC_HandleTypeDef *cdc = hUsbDeviceHS.pClassData;
    return hUsbDeviceHS.dev_state == USBD_STATE_CONFIGURED && cdc && !cdc->TxState;
}

/* Called with IRQs masked. Check DMA completion and queued work after masking,
   so an IRQ immediately before WFI cannot be lost until the next millisecond. */
static int work_pending(void)
{
    unsigned i;
    if (reply_length || reply_in_flight) return usb_ready();
    if (rx_read != rx_write || (usb_head != usb_tail && usb_ready())) return 1;
    if (!streaming || (int32_t)(HAL_GetTick() - settle_until) < 0) return 0;
    if (!capturing) return ready_events != seen_events;
    if (HAL_GetTick() - capture_started >= 10) return 1;
    for (i = 0; i < 4; ++i) if (HAL_SAI_GetState(sais[i]) != HAL_SAI_STATE_READY) return 0;
    return 1;
}

static void idle_if_possible(void)
{
    uint32_t primask = __get_PRIMASK();
    if (primask) return;
    __disable_irq();
    if (!work_pending()) {
        uint32_t start = runtime_micros();
        ++sleep_entries;
        runtime_sleep();
        window_wait_us += runtime_micros() - start;
    }
    __set_PRIMASK(primask);
}

static void poll(void)
{
    if (last_rx_dropped != rx_dropped) {
        /* Never execute a command truncated by queue overflow. Resync at newline. */
        uint32_t primask = __get_PRIMASK();
        __disable_irq();
        rx_read = rx_write;
        last_rx_dropped = rx_dropped;
        __set_PRIMASK(primask);
        memset(&parser, 0, sizeof(parser)); parser.overflow = 1;
    }
    if (reply_length) {
        /* Drain already acquired binary frames before beginning a text reply. */
        if (usb_head != usb_tail) { pump_usb(); return; }
        if (CDC_Transmit_HS((uint8_t *)reply, reply_length) == USBD_OK) {
            reply_length = 0; reply_in_flight = 1;
        }
        return;
    }
    if (reply_in_flight) {
        extern USBD_HandleTypeDef hUsbDeviceHS;
        uint32_t primask = __get_PRIMASK();
        int busy;
        USBD_CDC_HandleTypeDef *cdc;
        __disable_irq();
        cdc = hUsbDeviceHS.pClassData;
        busy = !cdc || cdc->TxState;
        __set_PRIMASK(primask);
        if (busy) return;
        reply_in_flight = 0;
#ifdef FREEEEG32_UF2_APPLICATION
        if (bootloader_after_reply) { uf2_request_bootloader(); NVIC_SystemReset(); }
#endif
        if (reboot_after_reply) NVIC_SystemReset();
        if (start_after_reply) { streaming = 1; start_after_reply = 0; seen_events = ready_events; }
    }
    if (rx_read != rx_write) {
        control_command cmd;
        __DMB();
        cmd = control_feed(&parser, rx[rx_read % sizeof(rx)]);
        ++rx_read;
        if (cmd.kind != CONTROL_NONE) command(cmd);
    }
    if (streaming && !reply_length && (int32_t)(HAL_GetTick() - settle_until) >= 0) acquire();
    if (!reply_length) pump_usb();
    diagnostics_update();
}

void FreeEEG32_Run(void)
{
    eeg_settings saved;
    reset_flags = runtime_init();
    settings_from_flash = settings_load(&saved);
    if (!select_sinc3() || !apply_settings(&saved)) streaming = 0;
    watchdog_init(HAL_GetTick());
    window_stamp = runtime_micros(); window_events = ready_events; window_acquired = acquired;
    for (;;) {
        uint32_t start = runtime_micros(), elapsed;
        poll();
        watchdog_service(HAL_GetTick());
        elapsed = runtime_micros() - start;
        if (streaming && !reply_length && elapsed > max_work_us) max_work_us = elapsed;
        idle_if_possible();
    }
}
