/* Host simulation checks logic and buffer lengths; it cannot validate electrical timing. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#ifdef _MSC_VER
#define __attribute__(x)
#endif
#include "../Src/freeeeg32.c"

SAI_HandleTypeDef hsai_BlockB2, hsai_BlockA1, hsai_BlockB1, hsai_BlockA2;
UART_HandleTypeDef huart1;
static ad7779_dev adc_devices[4];
ad7779_dev *devices[4] = { &adc_devices[0], &adc_devices[1], &adc_devices[2], &adc_devices[3] };
USBD_HandleTypeDef hUsbDeviceHS;
static USBD_CDC_HandleTypeDef test_cdc;
static unsigned tick, receives, usb_frames, stops, fail_receive, fail_read;
static int fail_adc = -1, corrupt_adc = -1;
static uint8_t transmitted[2048], settings_memory[SETTINGS_BYTES];
static uint32_t micros, sleeping, wake_dma, wake_drdy, usb_busy, transmitted_length;
uint32_t test_primask;
uint32_t runtime_init(void) { return 0x12340000; }
uint32_t runtime_micros(void) { return micros; }
void runtime_sleep(void) { assert(test_primask == 1); ++sleeping; micros += 20; }
int runtime_adc_spi_raw(unsigned adc, uint8_t *tx, uint8_t *rx, uint8_t length)
{ unsigned i; assert(adc < 4 && length <= 3); for (i = 0; i < length; ++i) rx[i] = (uint8_t)(tx[0] + i); return 0; }
static unsigned adc_syncs;
void runtime_adc_sync(void) { ++adc_syncs; }
const char *runtime_clock_source(void) { return "HSE"; }
int runtime_watchdog_start(void) { return 1; }
void runtime_watchdog_feed(void) { }
void test_set_primask(uint32_t mask)
{
    unsigned i;
    test_primask = mask;
    if (!mask && wake_dma) { for (i = 0; i < 4; ++i) sais[i]->state = 0; wake_dma = 0; }
    if (!mask && wake_drdy) { FreeEEG32_DataReady(ADC1_DRDY_Pin); wake_drdy = 0; }
}
int settings_read(uint32_t offset, uint32_t record[8])
{ assert(offset < SETTINGS_BYTES); memcpy(record, settings_memory + offset, 32); return 1; }
int settings_program(uint32_t offset, const uint32_t record[8])
{ unsigned i; for (i = 0; i < 32; ++i) assert(settings_memory[offset+i] == 255); memcpy(settings_memory+offset, record, 32); return 1; }
int settings_erase(void) { memset(settings_memory, 255, sizeof(settings_memory)); return 1; }
uint32_t SystemCoreClock = 80000000u;
uint32_t HAL_GetREVID(void) { return 0x2003; }
uint32_t HAL_RCC_GetHCLKFreq(void) { return 40000000u; }

uint32_t HAL_GetTick(void) { return tick; }
static uint32_t simulated_drdy_hz; /* DRDY events generated while HAL_Delay runs */
void HAL_Delay(uint32_t delay) { tick += delay; micros += delay * 1000; ready_events += delay * simulated_drdy_hz / 1000; }
int HAL_SAI_DMAStop(SAI_HandleTypeDef *sai) { ++stops; sai->state = 0; return 0; }
int HAL_SAI_GetState(SAI_HandleTypeDef *sai) { return sai->state; }
uint32_t HAL_SAI_GetError(SAI_HandleTypeDef *sai) { (void)sai; return 0; }
int HAL_SAI_Receive_DMA(SAI_HandleTypeDef *sai, uint8_t *buffer, uint16_t words)
{
    unsigned i;
    assert(words == 8); /* Regression: original passed 224 words into an eight-word buffer. */
    ++receives;
    if (fail_receive) return HAL_ERROR;
    for (i = 0; i < words; ++i) ((uint32_t *)buffer)[i] = 0xab123456u + i;
    sai->state = 1;
    return HAL_OK;
}
int HAL_UART_GetState(UART_HandleTypeDef *uart) { return uart->state; }
int HAL_UART_Transmit_DMA(UART_HandleTypeDef *uart, uint8_t *buffer, uint16_t length)
{ (void)uart; assert(length == 105); assert(buffer != frame); return 0; }
uint8_t CDC_Transmit_HS(uint8_t *buffer, uint16_t length)
{ if (usb_busy || test_cdc.TxState) return USBD_BUSY; assert(length <= sizeof(transmitted)); memcpy(transmitted, buffer, length); transmitted_length = length; ++usb_frames; return USBD_OK; }
int ad7779_spi_int_reg_read(ad7779_dev *dev, uint8_t reg, uint8_t *value)
{
    if (fail_read || (fail_adc >= 0 && dev == &adc_devices[fail_adc])) return -1;
    *value = corrupt_adc >= 0 && dev == &adc_devices[corrupt_adc] ? 0 : dev->regs[reg]; /* simulated mismatch */
    return 0;
}
int ad7779_spi_int_reg_write_mask(ad7779_dev *dev, uint8_t reg, uint8_t mask, uint8_t value)
{ dev->regs[reg] = (dev->regs[reg] & ~mask) | value; return 0; }
int ad7779_spi_int_reg_write(ad7779_dev *dev, uint8_t reg, uint8_t value)
{ dev->regs[reg] = value; return 0; }
int ad7779_set_dec_rate(ad7779_dev *dev, uint16_t integer, uint16_t fractional)
{
    assert(fractional == 0);
    dev->regs[96] = (uint8_t)(integer >> 8); dev->regs[97] = (uint8_t)integer;
    dev->regs[98] = dev->regs[99] = 0; return 0;
}
int ad7779_set_gain(ad7779_dev *dev, ad7779_ch channel, ad7779_gain gain)
{ dev->regs[channel] = (uint8_t)(gain << 6); return 0; }

static control_command line(const char *text)
{
    control_parser local = {0}; control_command result = {0};
    while (*text) result = control_feed(&local, (uint8_t)*text++);
    return result;
}

int main(void)
{
    unsigned i;
    control_parser local = {0}; control_command result;
    settings_erase(); settings_defaults(&current_settings);
    hUsbDeviceHS.pClassData = &test_cdc; hUsbDeviceHS.dev_state = USBD_STATE_CONFIGURED;
    assert(line("!rate 1024\n").kind == CONTROL_RATE);
    assert(line("!RATE 256\n").kind == CONTROL_ERROR);
    assert(line("!RATE -512\n").kind == CONTROL_ERROR);
    assert(line("!RATE 512junk\n").kind == CONTROL_ERROR);
    assert(line("!RATE 99999999999999\n").kind == CONTROL_ERROR);
    assert(line("!GAIN 32 8\n").kind == CONTROL_GAIN);
    assert(line("!SPIREAD 1 17\n").kind == CONTROL_SPIREAD);
    assert(line("!SPIREAD 5 17\n").kind == CONTROL_ERROR && line("!SPIREAD 1 128\n").kind == CONTROL_ERROR);
    assert(line("!SPIREAD 4 8\n").kind == CONTROL_SPIREAD && line("!GAIN 4 3\n").kind == CONTROL_ERROR);
    assert(line("!SPIWRITE 1 17 64\n").kind == CONTROL_SPIWRITE && line("!SPIWRITE 1 17 256\n").kind == CONTROL_ERROR);
    assert(line("!SPIWRITE 1 17 64\n").third == 64 && line("!GAIN 1 8 1\n").kind == CONTROL_ERROR);
    assert(line("!GAIN 0 8\n").kind == CONTROL_ERROR);
    assert(line("!GAIN 33 1\n").kind == CONTROL_ERROR);
    assert(line("!GAIN 1 3\n").kind == CONTROL_ERROR);
    assert(line("!START extra\n").kind == CONTROL_ERROR);
    assert(line("b\n").kind == CONTROL_NONE);
    assert(line("!BOO\n").kind == CONTROL_ERROR);
    assert(line("!HELP SETTINGS\n").kind == CONTROL_HELP);
    assert(line("!HELP extra junk\n").kind == CONTROL_ERROR);
    assert(line("!PRESET FAST\n").kind == CONTROL_PRESET);
    assert(line("!PRESET UNKNOWN\n").kind == CONTROL_ERROR);
    assert(line("!SAVE extra\n").kind == CONTROL_ERROR);
    /* Fragmented commands and CRLF produce exactly one command. */
    for (i = 0; i < 3; ++i) assert(control_feed(&local, (uint8_t)"!ST"[i]).kind == CONTROL_NONE);
    assert(control_feed(&local, 'O').kind == CONTROL_NONE);
    assert(control_feed(&local, 'P').kind == CONTROL_NONE);
    assert(control_feed(&local, '\r').kind == CONTROL_STOP);
    assert(control_feed(&local, '\n').kind == CONTROL_NONE);
    control_feed(&local, '!');
    for (i = 0; i < 200; ++i) control_feed(&local, 'A');
    assert(control_feed(&local, '\n').kind == CONTROL_ERROR);
    { unsigned syncs = adc_syncs;
    assert(set_rate(1024)); assert(rate == 1024 && adc_syncs == syncs + 1); }
    for (i = 0; i < 4; ++i) assert(adc_devices[i].regs[96] == 7 && adc_devices[i].regs[97] == 208);
    /* AD7771 SINC5 (FILTER_MODE) cannot reach 512 Hz; boot selects SINC3 and resyncs. */
    for (i = 0; i < 4; ++i) adc_devices[i].regs[18] = 0x49;
    { unsigned syncs = adc_syncs; assert(select_sinc3() && adc_syncs == syncs + 1); }
    for (i = 0; i < 4; ++i) assert(adc_devices[i].regs[18] == 0x09);
    assert(ready_events == 0); FreeEEG32_DataReady(2); assert(ready_events == 0);
    FreeEEG32_DataReady(ADC1_DRDY_Pin); acquire();
    assert(receives == 4 && capturing && acquired == 0);
    acquire(); assert(acquired == 0 && usb_frames == 0);
    for (i = 0; i < 4; ++i) sais[i]->state = 0;
    { unsigned stopped_before = stops;
      acquire(); pump_usb(); assert(stops == stopped_before + 4); }
    assert(acquired == 1 && usb_frames == 1 && !capturing);
    assert(transmitted[0] == 0xa0 && transmitted[104] == 0xc0);
    assert(transmitted[2] == 0x12 && transmitted[3] == 0x34 && transmitted[4] == 0x56);
    assert(transmitted_length == 105);
    for (i = 0; i < 5; ++i) acquire();
    assert(acquired == 1); /* Never send a second copy without a new complete capture. */
    ready_events += 3; acquire(); assert(missed == 2);
    tick += 11; acquire(); assert(dma_errors == 1 && !capturing);
    fail_receive = 1; ++ready_events; acquire(); assert(dma_errors == 2 && !capturing);
    fail_receive = 0;
    result = line("!GAIN 32 4\n"); command(result);
    assert(adc_devices[3].regs[7] == 128 && !strncmp(reply, "OK GAIN", 7));
    assert(!streaming && reply_length);
    /* Temporary USB backpressure queues frames; batches retain complete packets. */
    usb_busy = 1;
    { uint8_t expected = (uint8_t)sequence;
    for (i = 0; i < 20; ++i) { send_frame(); pump_usb(); }
    assert(usb_head - usb_tail == 16 && usb_dropped == 4 && usb_high_water == 16);
    usb_busy = 0;
    while (usb_head != usb_tail) {
        pump_usb(); assert(transmitted_length % 105 == 0);
        for (i = 0; i < transmitted_length; i += 105) {
            assert(transmitted[i] == 0xa0 && transmitted[i+104] == 0xc0);
            assert(transmitted[i+1] == expected++);
        }
    }
    }
    /* Text cannot overtake queued binary data or overwrite an in-flight transfer. */
    send_frame(); command(line("!STOP\n"));
    test_cdc.TxState = 1; poll(); assert(usb_head != usb_tail && reply_length);
    test_cdc.TxState = 0; poll(); assert(usb_head == usb_tail && reply_length && transmitted[0] == 0xa0);
    poll(); assert(reply_in_flight && !reply_length && !memcmp(transmitted, "OK STOP", 7));
    poll(); assert(!reply_in_flight);
    command(line("!PRESET FAST\n")); assert(rate == 2048 && current_settings.gains[31] == 8 && settings_dirty);
    command(line("!SAVE\n")); assert(!strcmp(reply, "OK SAVE\r\n") && !settings_dirty);
    command(line("!PRESET LOWGAIN\n")); assert(rate == 1024 && current_settings.gains[31] == 1);
    command(line("!LOAD\n")); assert(rate == 2048 && current_settings.gains[31] == 8 && !settings_dirty);
    command(line("!FACTORY\n")); assert(rate == 512 && current_settings.gains[31] == 8);
    command(line("!SETTINGS\n")); assert(strstr(reply, "source=saved dirty=0 gains=8,8"));
    command(line("!HELP\n")); assert(strstr(reply, "!SAVE") && strstr(reply, "!DIAG"));
    command(line("!HELP SETTINGS\n")); assert(strstr(reply, "persists"));
    command(line("!HELP PRESETS\n")); assert(strstr(reply, "FAST=2048Hz"));
    /* One-second wall-clock window, independent of the selected CPU frequency. */
    streaming = 1; settle_until = 0; micros = 1000; window_stamp = micros;
    window_events = ready_events; window_acquired = acquired; window_wait_us = 500000;
    micros += 1000000; ready_events += 2048; acquired += 2048;
    diagnostics_update();
    assert(measured_drdy_millihz == 2048000 && measured_capture_millihz == 2048000 && measured_wait_permille == 500);
    command(line("!DIAG\n")); assert(strstr(reply, "capture_millihz=2048000"));
    /* Never sleep over already queued RX, DRDY or DMA completion. IRQs that
       arrive in the masked WFI window are handled before the next poll. */
    reply_length = 0; reply_in_flight = 0; streaming = 0; capturing = 0;
    idle_if_possible(); assert(sleeping == 1 && !test_primask);
    rx[0] = 'x'; rx_write = 1; rx_read = 0;
    idle_if_possible(); assert(sleeping == 1); rx_read = rx_write;
    streaming = 1; seen_events = ready_events; settle_until = 0;
    wake_drdy = 1; idle_if_possible(); assert(sleeping == 2 && ready_events != seen_events);
    idle_if_possible(); assert(sleeping == 2);
    acquire(); assert(capturing);
    wake_dma = 1; idle_if_possible(); assert(sleeping == 3);
    idle_if_possible(); assert(sleeping == 3);
    acquire(); assert(!capturing); pump_usb();
    simulated_drdy_hz = 0; /* No DRDY: the measured rate fails every ADC. */
    command(line("!CHECK\n")); assert(strstr(reply, "adc_ok_mask=0x0 adc_failed_mask=0xf") && strstr(reply, "drdy_hz=0 rate_ok=0"));
    simulated_drdy_hz = rate;
    command(line("!CHECK\n")); assert(strstr(reply, "adc_ok_mask=0xf adc_failed_mask=0x0 adc_fault=0"));
    assert(strstr(reply, "rate_ok=1"));
    {
        /* A successful read with the wrong value is reported, but does not stop acquisition. */
        unsigned gain8 = current_settings.gains[8];
        corrupt_adc = 1;
        command(line("!CHECK\n")); assert(strstr(reply, "adc_ok_mask=0xd adc_failed_mask=0x2 adc_fault=0"));
        assert(strstr(reply, "readback_mask=0x2"));
        assert(set_gain(8, 4) && !adc_fault && current_settings.gains[8] == 4);
        corrupt_adc = -1; assert(set_gain(8, gain8)); readback_mask = 0;
    }
    fail_adc = 2;
    command(line("!CHECK\n")); assert(strstr(reply, "adc_ok_mask=0xb adc_failed_mask=0x4 adc_fault=1"));
    assert(strstr(reply, "last_adc=3") && strstr(reply, "last_op=READBACK"));
    fail_adc = -1;
    command(line("!CHECK\n")); assert(strstr(reply, "adc_ok_mask=0xf adc_failed_mask=0x0 adc_fault=1"));
    simulated_drdy_hz = 0; seen_events = ready_events;
    streaming = 1; command(line("!STOP\n")); assert(strstr(reply, "was_streaming=1"));
    command(line("!STOP\n")); assert(strstr(reply, "was_streaming=0"));
    watchdog_init(HAL_GetTick()); assert(watchdog_active());
    fail_read = 1; assert(!set_rate(2048) && adc_fault);
    command(line("!SPIREAD 2 17\n"));
    assert(strstr(reply, "adc=2 reg=0x11 f1=91,92 f2=91,92 f3=91,92,93 status=0,0,0 driver=") && reply_length < sizeof(reply));
    command(line("!SPIWRITE 3 17 64\n")); assert(strstr(reply, "adc=3 reg=0x11 value=0x40 rx=11,12 status=0"));
    command(line("!INFO\n")); assert(strstr(reply, "cpu_mhz=80 ahb_mhz=40"));
    assert(strstr(reply, "build=" FREEEEG32_BUILD_TAG) && reply_length < sizeof(reply));
    assert(strstr(reply, "watchdog=IWDG1") && strstr(reply, "clock=HSE"));
    SystemCoreClock = 40000000u;
    command(line("!INFO\n")); assert(strstr(reply, "cpu_mhz=40 ahb_mhz=40"));
    command(line("!START\n")); assert(!start_after_reply && !strncmp(reply, "ERR ADC", 7));
    { uint8_t input[600] = {0}; FreeEEG32_Receive(input, sizeof(input)); }
    assert(rx_write - rx_read == 512 && rx_dropped == 88);
    puts("Firmware simulation passed: controls/help, settings/presets, USB backpressure/batching, rates, DMA, diagnostics, race-safe sleep and RX bounds.");
    return 0;
}
