# ESP32 Geiger Counter

Handheld, battery-powered Geiger counter built around the **ESP32-S3-WROOM-1** and a Soviet **SBM-20** GM tube.

**Status: Work in progress.** The high-voltage supply has been prototyped on perfboard and regulates at 400 V (±1.5%). Tube and pulse-counting tests are in progress, and the full KiCad schematic is underway (PCB not started).

## Architecture

- **Battery:** 2S Li-ion pack (7.4 V nominal, 6.0–8.4 V)
- **Charging:** TI BQ25886 USB-C boost charger with power-path management
- **3.3 V rail:** Diodes AP63203 synchronous buck
- **MCU:** ESP32-S3 with native USB, so one USB-C port handles both charging and flashing (no USB-UART bridge)
- **High voltage:** firmware-regulated 7.4 V → 400 V discontinuous-mode boost
  - UCC27517 gate driver + STN1HNK60 600 V MOSFET + 10 mH inductor
  - 3×100 MΩ + 680 kΩ divider into an ADC for closed-loop hysteretic control
  - 450 V zener clamp and a firmware overvoltage cutoff
  - 1 MΩ / 10 nF ripple filter feeding the tube through a 5.1 MΩ anode resistor
- **Detection:** SBM-20 cathode pulse → 2N3904 shaper → ESP32 interrupt
- **Display:** 1.3" 128×64 I2C OLED (planned)

## Progress

- [x] HV boost designed and simulated in LTspice
- [x] Perfboard HV prototype: 400 V regulation verified
- [ ] SBM-20 background count test
- [ ] Full schematic (power, charger, ESP32, HV, display)
- [ ] PCB layout and assembly
- [ ] Firmware: CPM / µSv/h display, logging

## Tools

KiCad · LTspice · Arduino (ESP32 core) · C++

## ⚠️ Safety

This project generates **~400 V DC**. The stored energy is small, but don't touch the HV section while it's powered, and let the capacitors bleed down (watch the HV reading drop to 0) before handling the board.
