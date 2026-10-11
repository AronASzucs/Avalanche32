# ESP32 Geiger Counter

Handheld, battery-powered Geiger counter built around the **ESP32-S3-WROOM-1** and a Soviet **SBM-20** GM tube.

**Status: Work in progress.** The perfboard prototype of the high-voltage supply regulates up to 400 V and is detecting background radiation, with an audible click per count. The KiCad schematic is nearly complete; PCB layout is next.

## Architecture

- **Battery:** 2S Li-ion pack (7.4 V nominal, 6.0–8.4 V), 3 A polyfuse
- **Charging:** TI BQ25886 USB-C boost charger with power-path management
- **3.3 V rail:** Diodes AP63203 synchronous buck
- **MCU:** ESP32-S3 with native USB, so one USB-C port handles both charging and flashing (no USB-UART bridge); USBLC6-2 ESD protection
- **High voltage:** firmware-regulated 7.4 V → ~400 V discontinuous-mode boost
  - UCC27517 gate driver + STN1HNK60 600 V MOSFET + 10 mH inductor
  - 3×100 MΩ + 680 kΩ divider into an ADC for closed-loop hysteretic control
  - 450 V zener clamp (3×150 V) and a firmware overvoltage cutoff
  - 1 MΩ / 10 nF ripple filter feeding the tube through the anode resistor
- **Detection:** SBM-20 cathode pulse → 2N3904 shaper → ESP32 interrupt
- **Audio:** piezo transducer driven by a 2N7002 low-side switch, one click per count
- **Display:** 2.42" 128×64 SSD1309 OLED over SPI

## Progress

- [x] HV boost designed and simulated in LTspice
- [x] Perfboard HV prototype: 400 V regulation verified
- [x] SBM-20 background count test (~10–14 CPM indoors)
- [x] Test firmware: hysteretic HV control, rolling CPM, µSv/h estimate, piezo click
- [ ] Full schematic (power, charger, ESP32, HV, display): nearly complete
- [ ] PCB layout and assembly
- [ ] Final firmware: OLED display, logging, battery monitoring

## Known issue: Tube re-firing

The current SBM-20 sometimes fails to quench: instead of one pulse, it fires a burst of 100–1000+ pulses about 150–200 µs apart. Bursts happen at every voltage tested (330–380 V) and get more frequent at higher voltage, which points to a degraded tube. The firmware has an optional burst filter (`BURST_FILTER`): a count only registers after 5 ms of quiet, so each burst counts once. The test firmware tracks raw pulses and filtered counts separately for diagnostics. A replacement tube is on the way.

## Firmware

`Firmware/HV_Test/HV_Test.ino` is a bench test for the HV supply and counting chain (Arduino ESP32 core). Serial output at 115200 baud shows HV, total and raw counts, rolling CPM and an estimated µSv/h. Pins, the HV setpoint and the burst filter are set at the top of the file.

## Tools

KiCad · LTspice · Arduino (ESP32 core) · C++

## ⚠️ Safety

This project generates **~400 V DC**. The stored energy is small, but don't touch the HV section while it's powered, and let the capacitors bleed down (watch the HV reading drop to 0) before handling the board.
