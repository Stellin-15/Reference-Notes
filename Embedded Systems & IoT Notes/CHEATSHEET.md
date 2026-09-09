# Embedded Systems & IoT — In-Depth Reference

Firmware, microcontrollers, and the constraints (memory, power, real-time
guarantees) that don't exist in application/cloud development.


## 1. MICROCONTROLLERS VS MICROPROCESSORS

A **microcontroller** (MCU — ARM Cortex-M, AVR, ESP32) integrates CPU,
RAM, flash storage, and peripherals (GPIO, ADC, timers) on ONE chip,
running typically WITHOUT a full OS (bare-metal or a lightweight RTOS) —
kilobytes to a few megabytes of RAM, not gigabytes. A **microprocessor**
(ARM Cortex-A, x86) runs a full OS (Linux) and expects external RAM/
storage — Raspberry Pi-class devices sit here, not in MCU territory. This
distinction matters immediately for what's even POSSIBLE: you cannot run
a full Linux + Python + a web framework on a typical MCU — the resource
budget is measured in kilobytes, not gigabytes, and every design decision downstream follows from that.


## 2. REAL-TIME OPERATING SYSTEMS (RTOS)

**FreeRTOS** — the dominant open-source RTOS for MCUs — provides
preemptive task scheduling, queues, and semaphores in a tiny footprint
(kilobytes), letting embedded firmware have genuine multitasking without
a full OS's overhead. The core distinguishing property of "real-time" here
is DETERMINISTIC timing — a hard-real-time system must GUARANTEE a task
completes within a deadline, not just "usually be fast" — missing that
deadline in a genuinely hard-real-time system (an airbag controller, an
industrial safety interlock) is a system FAILURE, not just degraded
performance, a fundamentally different reliability bar than typical backend engineering.

```c
// FreeRTOS task creation — a genuinely different mental model than an OS process
void sensor_task(void *pvParameters) {
    for (;;) {
        float reading = read_sensor();
        xQueueSend(sensor_queue, &reading, portMAX_DELAY);
        vTaskDelay(pdMS_TO_TICKS(100));  // Yield for 100ms, cooperative with the scheduler
    }
}
xTaskCreate(sensor_task, "Sensor", 128, NULL, 2, NULL);  // Stack size in WORDS, not bytes — a real, common bug source
```

**Zephyr / mbed OS** — other embedded RTOS options, Zephyr in particular
gaining significant traction as a more modern, Linux-Foundation-governed
alternative with broader hardware support than FreeRTOS's more minimal scope.


## 3. COMMUNICATION PROTOCOLS

- **I2C** — two-wire, multi-device bus, simple, moderate speed — the
  standard for connecting sensors/peripherals on a single board.
- **SPI** — four-wire, faster than I2C, but needs a dedicated chip-select
  line per device — used when I2C's speed isn't enough (displays, SD cards, faster sensors).
- **UART** — simple point-to-point serial, the classic "debug console"
  and GPS-module/simple-sensor interface.
- **MQTT** (see Edge Computing deep dive) — the dominant IoT-to-cloud
  pub/sub protocol specifically because it's lightweight and designed for
  unreliable/low-bandwidth links, unlike HTTP's heavier assumptions.
- **BLE (Bluetooth Low Energy)** — the standard for battery-powered,
  short-range IoT devices (wearables, sensors) — GATT (Generic Attribute
  Profile) defines how BLE devices expose their data as
  services/characteristics that a phone app or gateway can read/write.
- **LoRaWAN / Zigbee / Z-Wave** — longer-range (LoRaWAN, kilometers, very
  low power) or mesh-networked (Zigbee/Z-Wave, common in smart-home
  devices) protocols — chosen specifically when WiFi's power consumption
  or BLE's range is insufficient for the use case.


## 4. POWER & RESOURCE CONSTRAINTS

Battery-powered embedded devices live and die by power budget — a device
that should last a year on a coin-cell battery can't afford to keep its
radio/CPU active continuously. **Sleep modes** (deep sleep, where most of
the chip is powered down except a wake-up timer/interrupt source) are the
primary lever — firmware architecture explicitly optimizes for "wake up,
do the minimum necessary work, go back to sleep" rather than
continuously-running application-style code. **Watchdog timers** —
hardware that automatically RESETS the device if firmware fails to
"check in" periodically — the embedded-world answer to "what happens if
my code hangs," since there's often no operator watching a dashboard to notice and intervene.


## 5. NICHE BUT REAL

- **Interrupt Service Routines (ISRs)** — hardware-triggered code that
  preempts normal execution immediately on an event (a button press, a
  timer expiring, data arriving on a UART) — ISRs must be extremely FAST
  and avoid blocking operations (no `printf`, no dynamic memory
  allocation in many embedded contexts) because they run with interrupts
  disabled and can starve other critical timing if they run too long — a
  real, foundational embedded-programming discipline with no direct application-development analogue.
- **Memory-mapped I/O** — on embedded systems, PERIPHERALS (GPIO
  registers, timers, ADCs) are accessed by reading/writing to SPECIFIC
  MEMORY ADDRESSES, not through OS syscalls — `*(volatile uint32_t
  *)0x40020014 = 0x1;` toggles a GPIO pin directly — the `volatile`
  keyword here is load-bearing: without it, the compiler could optimize
  away what looks like a "redundant" memory write, a genuinely common
  embedded C bug.
- **Over-the-air (OTA) firmware updates** — updating deployed devices'
  firmware remotely, needing a FAIL-SAFE mechanism (a bootloader that can
  roll back to the previous known-good firmware if an update fails/
  corrupts) since a bricked remote IoT device in the field may be
  physically inaccessible — a real, significant engineering challenge distinct from typical software deployment.
- **Hardware-in-the-loop (HIL) testing** — testing firmware against
  simulated/real sensor hardware rather than pure software mocks, because
  embedded bugs frequently involve genuine timing/electrical behavior a
  pure software simulation can't fully capture — a distinct testing
  discipline from typical application unit/integration testing (see
  Testing & QA Engineering Notes for the general testing-pyramid
  framework this specializes for embedded's unique constraints).
