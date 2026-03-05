# Makefile for State Variable Oscillator - ADuCM362 firmware
#
# Prerequisites:
#   arm-none-eabi-gcc (ARM embedded toolchain)
#   ADuCM362 CMSIS pack (ADuCM360.h header + startup + linker script)
#
# Set CMSIS_DIR to point to your ADuCM36x device pack, e.g.:
#   make CMSIS_DIR=/path/to/ADuCM360/CMSIS
#
# The ADuCM362 uses the same register definitions as ADuCM360.

# ── Toolchain ──
CROSS   = arm-none-eabi-
CC      = $(CROSS)gcc
AS      = $(CROSS)gcc
LD      = $(CROSS)gcc
OBJCOPY = $(CROSS)objcopy
SIZE    = $(CROSS)size

# ── Device ──
CPU     = cortex-m3
DEVICE  = ADuCM362

# ── Paths ──
# Set CMSIS_DIR to your ADuCM360 device pack location
CMSIS_DIR  ?= ../../cn0359/EVAL-CN0359-EB1Z/ADuCM360_HAL_Driver
CMSIS_INC  = $(CMSIS_DIR)/include
STARTUP    = $(CMSIS_DIR)/source/startup_ADuCM360.s
LINKER_SCR = $(CMSIS_DIR)/source/ADuCM360.ld

# ── Sources ──
SRCS = osc_main.c \
       osc_system_init.c \
       osc_dac7800.c \
       osc_freq_measure.c \
       osc_calibrate.c \
       osc_uart.c

OBJS = $(SRCS:.c=.o) startup_ADuCM360.o

# ── Output ──
TARGET = osc_firmware
ELF    = $(TARGET).elf
BIN    = $(TARGET).bin
HEX    = $(TARGET).hex
MAP    = $(TARGET).map

# ── Flags ──
CFLAGS  = -mcpu=$(CPU) -mthumb
CFLAGS += -Os -g -Wall -Wextra
CFLAGS += -ffunction-sections -fdata-sections
CFLAGS += -I. -I$(CMSIS_INC)
CFLAGS += -D$(DEVICE)
CFLAGS += -std=c11

ASFLAGS = -mcpu=$(CPU) -mthumb -g

LDFLAGS  = -mcpu=$(CPU) -mthumb
LDFLAGS += -T$(LINKER_SCR)
LDFLAGS += -Wl,--gc-sections
LDFLAGS += -Wl,-Map=$(MAP)
LDFLAGS += --specs=nano.specs
LDFLAGS += -lm

# ── Build Rules ──

all: $(BIN) $(HEX) size

$(ELF): $(OBJS)
	$(LD) $(LDFLAGS) -o $@ $^

$(BIN): $(ELF)
	$(OBJCOPY) -O binary $< $@

$(HEX): $(ELF)
	$(OBJCOPY) -O ihex $< $@

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

startup_ADuCM360.o: $(STARTUP)
	$(AS) $(ASFLAGS) -c -o $@ $<

size: $(ELF)
	$(SIZE) $<

clean:
	rm -f $(OBJS) $(ELF) $(BIN) $(HEX) $(MAP)

.PHONY: all clean size
