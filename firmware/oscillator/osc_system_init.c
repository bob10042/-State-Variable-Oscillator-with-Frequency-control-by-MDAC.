/**
 * osc_system_init.c - ADuCM362 system initialization for oscillator
 *
 * Standalone init (not shared with TIA/electrometer project).
 * Configures:
 *   - 16 MHz internal oscillator (HFOSC)
 *   - SysTick for 1ms system tick
 *   - Peripheral clock enables
 *   - Power management for unused peripherals
 */

#include "osc_config.h"

/* ── System tick counter (1ms) ── */
static volatile uint32_t tick_ms = 0;

uint32_t get_tick_ms(void)
{
    return tick_ms;
}

void delay_ms(uint32_t ms)
{
    uint32_t start = tick_ms;
    while ((tick_ms - start) < ms) {
        __WFI();  /* sleep until next interrupt */
    }
}

/**
 * SysTick interrupt handler - increments 1ms counter.
 */
void SysTick_Handler(void)
{
    tick_ms++;
}

/**
 * Initialize all system clocks and peripherals.
 * Call this first in main().
 */
void system_init(void)
{
    /*
     * Clock configuration:
     *   HFOSC = 16 MHz (default, already running at reset)
     *   HCLK = 16 MHz (no divider)
     *   PCLK = 16 MHz (no divider)
     */
    pADI_CLKCTL->CLKCON0 = CLKCON0_CLKMUX_HFOSC  /* Use HFOSC */
                          | CLKCON0_CLKOUT_UCLK;   /* CLKOUT disabled */

    /* No clock divider: HCLK = PCLK = 16 MHz */
    pADI_CLKCTL->CLKCON1 = 0;

    /*
     * Enable peripheral clocks:
     *   SPI0  - DAC7800 communication
     *   UART  - Host communication
     *   Timer1 - Frequency measurement (capture mode)
     *   ADC0  - AD636 RMS reading
     *   GPIO  - Always enabled
     *
     * Disable unused peripherals:
     *   SPI1, I2C, Timer0, DMA, DAC, PWM
     */
    pADI_CLKCTL->CLKDIS = CLKDIS_DISSPI1CLK_MSK   /* Disable SPI1 */
                         | CLKDIS_DISI2CCLK_MSK    /* Disable I2C */
                         | CLKDIS_DIST0CLK_MSK     /* Disable Timer0 */
                         | CLKDIS_DISDMACLK_MSK    /* Disable DMA */
                         | CLKDIS_DISDACCLK_MSK;   /* Disable DAC */

    /*
     * SysTick: 1ms interrupt for timing.
     *   Reload = 16,000,000 / 1000 - 1 = 15999
     */
    SysTick->LOAD = SYSTICK_RELOAD;
    SysTick->VAL  = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk   /* CPU clock */
                  | SysTick_CTRL_TICKINT_Msk      /* Enable interrupt */
                  | SysTick_CTRL_ENABLE_Msk;      /* Enable SysTick */

    /* Set SysTick to lowest priority */
    NVIC_SetPriority(SysTick_IRQn, 15);
}
