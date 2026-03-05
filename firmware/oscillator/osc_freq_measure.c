/**
 * osc_freq_measure.c - Frequency and amplitude measurement
 *
 * Frequency: Timer1 in capture mode on P0.5 (BP zero-crossing).
 *   The oscillator BP output is AC-coupled through a 1uF cap and biased
 *   to mid-supply via 100k/100k divider. The GPIO Schmitt trigger input
 *   detects zero-crossings. Timer1 captures the timestamp on each rising
 *   edge. Period = capture[n+1] - capture[n].
 *
 *   Timer1 runs from PCLK (16 MHz), giving:
 *     At 25 Hz:  period = 640,000 counts (0.004% resolution)
 *     At 30 kHz: period = 533 counts (0.19% resolution, average for better)
 *
 * Amplitude: ADC0 reads AD636 RMS output on AIN0.
 *   AD636 output: 0-200mV DC (proportional to oscillator RMS)
 *   ADC: 24-bit sigma-delta, PGA=4, Vref=1.2V internal
 *   Range: +/-300mV (1.2V / 4)
 *   Resolution: 1.2V / (4 * 2^23) = 35.8 nV per LSB
 */

#include "osc_config.h"
#include "osc_freq_measure.h"

/* External functions from shared modules */
extern uint32_t get_tick_ms(void);
extern void delay_ms(uint32_t ms);

/* Timer1 capture state */
static volatile uint32_t cap_value    = 0;
static volatile bool     cap_ready    = false;
static volatile uint32_t cap_overflow = 0;

/* ADC state */
static volatile int32_t  adc0_result  = 0;
static volatile bool     adc0_ready   = false;

/**
 * Timer1 capture interrupt handler.
 * Called on rising edge of BP zero-crossing input.
 */
void GP_Tmr1_Int_Handler(void)
{
    if (pADI_TM1->STA & T1STA_CAP_MSK) {
        cap_value = pADI_TM1->CAP;
        cap_ready = true;
        pADI_TM1->CLRI = T1CLRI_CAP_CLR;  /* clear capture interrupt */
    }
    if (pADI_TM1->STA & T1STA_TMOUT_MSK) {
        cap_overflow++;
        pADI_TM1->CLRI = T1CLRI_TMOUT_CLR;
    }
}

/**
 * ADC0 conversion complete interrupt.
 */
void ADC0_Int_Handler(void)
{
    adc0_result = (int32_t)pADI_ADC0->DAT;
    adc0_ready = true;
}

void freq_measure_init(void)
{
    /*
     * Configure P0.5 as Timer1 capture input.
     * The GP0CON register needs bit pair for P0.5 set to Timer1 function.
     */
    pADI_GP0->GPCON = (pADI_GP0->GPCON & ~GP0CON_CON5_MSK)
                     | (2u << (5 * 2));  /* AF2 = T1CAP on P0.5 */
    pADI_GP0->GPOEN &= ~(1u << ZC_BIT); /* input */

    /*
     * Timer1 configuration:
     *   Clock source: PCLK (16 MHz) with prescaler /1
     *   Free-running mode (count up continuously)
     *   Capture on rising edge
     *   Enable capture interrupt
     */
    pADI_TM1->CON = T1CON_PRE_DIV1       /* No prescaler: 16 MHz */
                   | T1CON_CLK_PCLK       /* PCLK source */
                   | T1CON_MOD_FREERUN     /* Free-running mode */
                   | T1CON_UP_EN           /* Count up */
                   | T1CON_ENABLE_EN;      /* Enable timer */

    /* Load max value (16-bit timer wraps at 65535) */
    pADI_TM1->LD = 0xFFFF;

    /* Enable capture on rising edge */
    pADI_TM1->CON |= T1CON_EVENT_RISE;

    /* Enable Timer1 interrupt in NVIC */
    NVIC_SetPriority(TIMER1_IRQn, 2);
    NVIC_EnableIRQ(TIMER1_IRQn);

    /*
     * ADC0 for AD636 RMS reading:
     *   PGA gain = 4 (for 0-300mV range)
     *   Internal 1.2V reference
     *   AIN0 positive, AGND negative
     *   Chop enabled for offset cancellation
     *   Sinc3 filter, moderate speed (~10 Hz)
     */
    pADI_CLKCTL->CLKDIS &= ~CLKDIS_DISADCCLK_MSK;
    pADI_ANA->REFCTRL = REFCTRL_REFPD_DIS;

    pADI_ADC0->MDE = ADC0MDE_PGA_G4       /* PGA = 4 for 300mV range */
                   | ADC0MDE_ADCMOD2_MOD2OFF
                   | ADC0MDE_ADCMD_IDLE;

    pADI_ADC0->FLT = ADC0FLT_CHOP_ON
                    | ADC0FLT_RAVG2_ON
                    | ADC0FLT_SINC4EN_DIS
                    | (7 << 8)             /* AF = 7 */
                    | ADC0FLT_NOTCH2_EN
                    | 63;                  /* SF = 63, ~10 Hz output rate */

    pADI_ADC0->CON = ADC0CON_ADCEN_DIS
                   | ADC0CON_ADCCODE_INT
                   | ADC0CON_BUFPOWN_EN
                   | ADC0CON_BUFPOWP_EN
                   | ADC0CON_BUFBYPP_EN
                   | ADC0CON_BUFBYPN_EN
                   | ADC0CON_ADCREF_INTREF  /* 1.2V internal reference */
                   | ADC0CON_ADCDIAG_DIAG_OFF
                   | ADC0CON_ADCCP_AIN0
                   | ADC0CON_ADCCN_AGND;

    pADI_ADC0->MSKI = ADC0MSKI_RDY_EN;

    NVIC_SetPriority(ADC0_IRQn, 1);
    NVIC_EnableIRQ(ADC0_IRQn);
}

float freq_measure_period_s(void)
{
    uint32_t timeout_ms = 2000;  /* 2 second timeout (allows down to 0.5 Hz) */

    /* Wait for first rising edge */
    cap_ready = false;
    uint32_t start = get_tick_ms();
    while (!cap_ready) {
        if ((get_tick_ms() - start) > timeout_ms)
            return 0.0f;  /* timeout: no oscillation */
        __WFI();
    }
    uint32_t cap1 = cap_value;
    uint16_t ovf1 = cap_overflow;

    /* Wait for second rising edge */
    cap_ready = false;
    start = get_tick_ms();
    while (!cap_ready) {
        if ((get_tick_ms() - start) > timeout_ms)
            return 0.0f;
        __WFI();
    }
    uint32_t cap2 = cap_value;
    uint16_t ovf2 = cap_overflow;

    /* Calculate period in timer counts */
    uint32_t delta;
    if (cap2 >= cap1) {
        delta = cap2 - cap1 + (uint32_t)(ovf2 - ovf1) * 65536UL;
    } else {
        /* Timer wrapped */
        delta = (65536UL - cap1) + cap2 + (uint32_t)(ovf2 - ovf1 - 1) * 65536UL;
    }

    if (delta == 0) return 0.0f;

    /* Convert to seconds: period = delta / 16e6 */
    return (float)delta / (float)SYSCLK_HZ;
}

float freq_measure_hz(uint16_t num_periods)
{
    if (num_periods == 0) num_periods = 1;
    if (num_periods > 100) num_periods = 100;

    float total_period = 0.0f;
    uint16_t good_count = 0;

    for (uint16_t i = 0; i < num_periods; i++) {
        float p = freq_measure_period_s();
        if (p > 0.0f) {
            total_period += p;
            good_count++;
        }
    }

    if (good_count == 0) return 0.0f;

    float avg_period = total_period / (float)good_count;
    return 1.0f / avg_period;
}

float read_ad636_rms(void)
{
    adc0_ready = false;

    /* Trigger single conversion */
    pADI_ADC0->MDE = (pADI_ADC0->MDE & ~ADC0MDE_ADCMD_MSK)
                   | ADC0MDE_ADCMD_SINGLE;
    pADI_ADC0->CON |= ADC0CON_ADCEN_EN;

    /* Wait for result */
    uint32_t start = get_tick_ms();
    while (!adc0_ready) {
        if ((get_tick_ms() - start) > 500) {
            pADI_ADC0->CON &= ~ADC0CON_ADCEN_EN;
            return 0.0f;
        }
        __WFI();
    }

    /* Convert ADC raw to voltage at AD636 output */
    float v_adc = (float)adc0_result * ADC_VREF / (ADC_PGA_GAIN * ADC_FULLSCALE);

    /* Undo 1/5 attenuator to get oscillator RMS */
    float v_rms = v_adc * AD636_ATTEN_RATIO;

    return v_rms;
}
