"""Materialize the pinned 80 MHz source archive and apply the reviewed Beta patches.

Generated sources go in Firmware/build/source. Edit Beta sources, not that directory.
No network downloads or third party Python packages are required.
"""
from pathlib import Path, PurePosixPath
import hashlib
import shutil
import tarfile

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE.parent / 'Base' / 'STM32H743ZI_beta_80MHz_makefile.tar.gz'
ARCHIVE_SHA256 = '8ea26644227925d6897f4353a4022a1b1bd587ad19ab3097487a73331da01573'
SOURCE = HERE.parent / 'build' / 'source'


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError(f'Base source changed: expected {count} matches for {old[:90]!r}')
    return text.replace(old, new)


def prepare():
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Base archive SHA256 mismatch; refusing to patch unknown firmware')
    SOURCE.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ARCHIVE) as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts[1:]
            if not member.isfile() or not parts or parts[0] == 'build':
                continue
            if '..' in parts or any(':' in p for p in parts):
                raise ValueError('Unsafe archive member')
            target = SOURCE.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())

    def edit(name, transform):
        path = SOURCE / name
        path.write_text(transform(path.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')

    def main(s):
        s = replace(s, '#include "main.h"', '#include "main.h"\n#include "freeeeg32.h"\n#include "clock_profile.h"')
        s = replace(s, 'RCC_ClkInitStruct.SYSCLKDivider = RCC_SYSCLK_DIV1;',
                    'RCC_ClkInitStruct.SYSCLKDivider = FREEEEG32_CORE_DIVIDER;')
        s = replace(s, 'RCC_ClkInitStruct.AHBCLKDivider = RCC_HCLK_DIV2;',
                    'RCC_ClkInitStruct.AHBCLKDivider = FREEEEG32_AHB_DIVIDER;')
        s = replace(s, '__HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);',
                    '__HAL_RCC_SYSCFG_CLK_ENABLE();\n  if (HAL_PWREx_ControlVoltageScaling(FREEEEG32_VOLTAGE_SCALE) != HAL_OK) Error_Handler();')
        for old, new in (('PLLN = 10', 'PLLN = FREEEEG32_PLL_N'),
                         ('PLLQ = 2', 'PLLQ = FREEEEG32_PLL_QR'),
                         ('PLLR = 2', 'PLLR = FREEEEG32_PLL_QR'),
                         ('PLLVCOSEL = RCC_PLL1VCOMEDIUM', 'PLLVCOSEL = FREEEEG32_PLL_VCO'),
                         ('&RCC_ClkInitStruct, FLASH_LATENCY_0', '&RCC_ClkInitStruct, FREEEEG32_FLASH_LATENCY')):
            s = replace(s, old, new)
        # Run the H7 from its crystal (Y2, HSE) instead of the internal HSI oscillator, which
        # left every H7 timer about 0.4 % off. USB (HSI48), USART1 and the SPI/SAI kernel
        # clocks (CKPER = HSI) are unchanged. If Y2 does not start, fall back to HSI.
        s = replace(s, '  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI48|RCC_OSCILLATORTYPE_HSI;\n',
                    '  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI48|RCC_OSCILLATORTYPE_HSI|RCC_OSCILLATORTYPE_HSE;\n'
                    '  RCC_OscInitStruct.HSEState = RCC_HSE_ON;\n')
        s = replace(s, '  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;\n  RCC_OscInitStruct.PLL.PLLM = 4;\n'
                       '  RCC_OscInitStruct.PLL.PLLN = FREEEEG32_PLL_N;\n  RCC_OscInitStruct.PLL.PLLP = 2;\n'
                       '  RCC_OscInitStruct.PLL.PLLQ = FREEEEG32_PLL_QR;\n  RCC_OscInitStruct.PLL.PLLR = FREEEEG32_PLL_QR;\n',
                    '  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;\n  RCC_OscInitStruct.PLL.PLLM = FREEEEG32_HSE_PLLM;\n'
                    '  RCC_OscInitStruct.PLL.PLLN = FREEEEG32_HSE_PLLN;\n  RCC_OscInitStruct.PLL.PLLP = FREEEEG32_HSE_PLLP;\n'
                    '  RCC_OscInitStruct.PLL.PLLQ = FREEEEG32_HSE_PLLQR;\n  RCC_OscInitStruct.PLL.PLLR = FREEEEG32_HSE_PLLQR;\n')
        s = replace(s, '  RCC_OscInitStruct.PLL.PLLFRACN = 0;\n  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)\n  {\n    Error_Handler();\n  }\n',
                    '  RCC_OscInitStruct.PLL.PLLFRACN = 0;\n  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)\n  {\n'
                    '    /* Y2 did not start: run from the internal HSI oscillator as before. */\n'
                    '    RCC_OscInitStruct.HSEState = RCC_HSE_OFF;\n'
                    '    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;\n    RCC_OscInitStruct.PLL.PLLM = 4;\n'
                    '    RCC_OscInitStruct.PLL.PLLN = FREEEEG32_PLL_N;\n    RCC_OscInitStruct.PLL.PLLP = 2;\n'
                    '    RCC_OscInitStruct.PLL.PLLQ = FREEEEG32_PLL_QR;\n    RCC_OscInitStruct.PLL.PLLR = FREEEEG32_PLL_QR;\n'
                    '    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK) Error_Handler();\n  }\n')
        # USB is available before starting lengthy ADC and optional SD initialization.
        s = replace(s, '    BSP_SD_Init();', '    /* SD initialization is optional; no card is required to acquire EEG. */')
        s = replace(s, '      int ad_adc1=0;', '      int ad_adc1=0;\n      FreeEEG32_Run(); /* Default 32-channel acquisition and USB control loop. */')
        s = replace(s, 'void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)\n{',
                    'void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)\n{\n  FreeEEG32_DataReady(GPIO_Pin);\n  return; /* Acquisition runs in main, never in the EXTI handler. */')
        # Fix every legacy DMA call as well: SAI_DATASIZE_32 is a 224 bitmask, not a length.
        s = s.replace(', SAI_DATASIZE_32);', ', uint8_ad_chan_number);')
        return s
    edit('Src/main.c', main)
    # Y2 is 16 MHz (BOM, bench-confirmed); the base configuration said 32 MHz. Keep in
    # step with FREEEEG32_HSE_HZ in clock_profile.h.
    edit('Inc/stm32h7xx_hal_conf.h', lambda s: replace(s, '#define HSE_VALUE    ((uint32_t)32000000)',
                                                       '#define HSE_VALUE    ((uint32_t)16000000)'))
    # Application settings probe supplies a precise, ECC-aware BusFault handler.
    edit('Src/stm32h7xx_it.c', lambda s: replace(s, 'void BusFault_Handler(void)',
                                              'void Legacy_BusFault_Handler(void)'))

    def adc(s):
        # Status codes here are spi_write_and_read's: 0 = OK, -1 = error. Do not compare
        # them with SUCCESS: ad7779.h defines SUCCESS as 1, which made every read return
        # early without a value and kept the register cache (used by every RMW) at zero.
        # Setup previously tested an uninitialized pointer and ORed an uninitialized status.
        s = replace(s, '\tad7779_dev *dev;\n\tuint8_t i;\n\tint32_t ret;',
                    '\tad7779_dev *dev = NULL;\n\tuint8_t i;\n\tint32_t ret = 0;')
        s = replace(s, 'malloc(sizeof(*dev))', 'calloc(1, sizeof(*dev))', 2)
        s = replace(s, '\t*reg_data = rxbuf[1];', '\tif (ret != 0) return ret;\n\t*reg_data = rxbuf[1];')
        s = replace(s, '  uint8_t reg_data;\n  for(uint8_t reg_addr', '  uint8_t reg_data = 0;\n  for(uint8_t reg_addr')
        s = replace(s, 'dev->dec_rate_int = dec_val;', 'dev->dec_rate_dec = dec_val;', 2)
        s = replace(s, '*dec_val = dev->dec_rate_int;', '*dec_val = dev->dec_rate_dec;')
        # The API uses thousandths; do not store the converted Q16 register value in the cache.
        s = replace(s, 'uint8_t lsb;\n\n\tif (dev->ctrl_mode == AD7779_PIN_CTRL)',
                    'uint8_t lsb;\n\tuint16_t original_dec = dec_val;\n\n'
                    '\tif (!int_val || int_val > 4095 || dec_val > 999) return -1;\n'
                    '\tif (dev->ctrl_mode == AD7779_PIN_CTRL)')
        s = s.replace('dev->dec_rate_dec = dec_val;', 'dev->dec_rate_dec = original_dec;')
        s = replace(s, '\tdev->cached_reg_val[reg_addr] = reg_data;',
                    '\tif (ret == 0) dev->cached_reg_val[reg_addr] = reg_data;')
        return s
    edit('Src/ad7779.c', adc)

    # A GPIO pin mask must be 16 bits, even though the legacy hardware-NSS path ignores it.
    for name in ('Src/platform_drivers.c', 'Inc/platform_drivers.h'):
        edit(name, lambda s: s.replace('uint8_t chip_select_pin,', 'uint16_t chip_select_pin,'))
    def spi(s):
        start = s.index('int32_t spi_write_and_read(')
        end = s.index('/***************************************************************************//**', start)
        return s[:start] + '''int32_t spi_write_and_read(SPI_HandleTypeDef *spi_dev,
    GPIO_TypeDef *chip_select_port, uint16_t chip_select_pin,
    uint8_t *txdata, uint8_t *rxdata, uint8_t length)
{
    HAL_StatusTypeDef result;
    if (SPI_NSS_SOFTWARE) HAL_GPIO_WritePin(chip_select_port, chip_select_pin, GPIO_PIN_RESET);
    result = HAL_SPI_TransmitReceive(spi_dev, txdata, rxdata, length, 20);
    if (SPI_NSS_SOFTWARE) HAL_GPIO_WritePin(chip_select_port, chip_select_pin, GPIO_PIN_SET);
    return result == HAL_OK ? 0 : -1;
}

''' + s[end:]
    edit('Src/platform_drivers.c', spi)

    def usb(s):
        s = replace(s, '#include "usbd_cdc_if.h"', '#include "usbd_cdc_if.h"\n#include "freeeeg32.h"\n#include <string.h>')
        s = replace(s, '/* USER CODE BEGIN PV */', '/* USER CODE BEGIN PV */\nstatic uint8_t line_coding[7] = {0x00,0xc2,0x01,0x00,0,0,8};\nstatic uint16_t control_lines;')
        s = replace(s, '  case CDC_SET_LINE_CODING:\n\n    break;',
                    '  case CDC_SET_LINE_CODING:\n    if (length == sizeof(line_coding)) memcpy(line_coding, pbuf, sizeof(line_coding));\n    break;')
        s = replace(s, '  case CDC_GET_LINE_CODING:\n\n    break;',
                    '  case CDC_GET_LINE_CODING:\n    if (length == sizeof(line_coding)) memcpy(pbuf, line_coding, sizeof(line_coding));\n    break;')
        s = replace(s, '  case CDC_SET_CONTROL_LINE_STATE:\n\n    break;',
                    '  case CDC_SET_CONTROL_LINE_STATE:\n    control_lines = ((USBD_SetupReqTypedef *)pbuf)->wValue;\n    break;')
        s = replace(s, '  /* USER CODE BEGIN 11 */', '  /* USER CODE BEGIN 11 */\n  FreeEEG32_Receive(Buf, *Len);')
        s = replace(s, '  if (hcdc->TxState != 0){',
                    '  if (hUsbDeviceHS.dev_state != USBD_STATE_CONFIGURED || hcdc == NULL) { __set_PRIMASK(primask); return USBD_FAIL; }\n'
                    '  if (Len > sizeof(UserTxBufferHS)) { __set_PRIMASK(primask); return USBD_FAIL; }\n'
                    '  if (hcdc->TxState != 0){')
        s = replace(s, '  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef*)hUsbDeviceHS.pClassData;',
                    '  uint32_t primask = __get_PRIMASK();\n  __disable_irq();\n'
                    '  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef*)hUsbDeviceHS.pClassData;')
        s = replace(s, '    return USBD_BUSY;', '    __set_PRIMASK(primask);\n    return USBD_BUSY;')
        s = replace(s, '  USBD_CDC_SetTxBuffer(&hUsbDeviceHS, Buf, Len);',
                    '  memcpy(UserTxBufferHS, Buf, Len); /* Own data until USB IN completion. */\n'
                    '  USBD_CDC_SetTxBuffer(&hUsbDeviceHS, UserTxBufferHS, Len);')
        s = replace(s, '  result = USBD_CDC_TransmitPacket(&hUsbDeviceHS);',
                    '  result = USBD_CDC_TransmitPacket(&hUsbDeviceHS);\n  __set_PRIMASK(primask);')
        return s
    edit('Src/usbd_cdc_if.c', usb)
    edit('Src/usbd_desc.c', lambda s: s.replace('"STMicroelectronics"', '"FreeEEG32"').replace('"STM32 Virtual ComPort"', '"FreeEEG32 EEG + Control"'))
    # HSI48 USB clock accuracy is recovered from USB SOF with the H7 CRS peripheral.
    def clock(s):
        s = replace(s, '  HAL_PWREx_EnableUSBVoltageDetector();', '''  HAL_PWREx_EnableUSBVoltageDetector();
  __HAL_RCC_CRS_CLK_ENABLE();
  RCC_CRSInitTypeDef crs = {0};
  crs.Prescaler = RCC_CRS_SYNC_DIV1;
  crs.Source = RCC_CRS_SYNC_SOURCE_USB1; /* USB1 = OTG_HS, the port wired to PB14/PB15. */
  crs.Polarity = RCC_CRS_SYNC_POLARITY_RISING;
  crs.ReloadValue = __HAL_RCC_CRS_RELOADVALUE_CALCULATE(48000000, 1000);
  crs.ErrorLimitValue = RCC_CRS_ERRORLIMIT_DEFAULT;
  crs.HSI48CalibrationValue = RCC_CRS_HSI48CALIBRATION_DEFAULT;
  HAL_RCCEx_CRSConfig(&crs);''')
        return s
    edit('Src/usb_device.c', clock)
    # The generated suspend callback stops the PHY clock, but neither the HAL reset nor the
    # resume path restarts it, so a suspend (e.g. data cable connected after boot) leaves the
    # device unable to answer the next enumeration. The board is self-powered: keep it running.
    def usb_conf(s):
        s = replace(s, '  __HAL_PCD_GATE_PHYCLOCK(hpcd);\n',
                    '  /* PHY clock deliberately not gated: nothing restarts it on reset/resume. */\n')
        s = replace(s, '  /* USER CODE BEGIN 3 */\n',
                    '  /* USER CODE BEGIN 3 */\n  __HAL_PCD_UNGATE_PHYCLOCK(hpcd);\n')
        return s
    edit('Src/usbd_conf.c', usb_conf)
    # DMA scratch memory has no flash image. Without NOLOAD, objcopy fills the entire
    # address gap from internal flash to SRAM, producing a ~640 MB binary.
    edit('STM32H743ZITx_FLASH.ld', lambda s: replace(s, '.dma_buffer :', '.dma_buffer (NOLOAD) :'))
    for directory in ('Inc', 'Src'):
        for source in (HERE / directory).iterdir():
            shutil.copy2(source, SOURCE / directory / source.name)
    print(f'Prepared {SOURCE}')
    return SOURCE


if __name__ == '__main__':
    prepare()
