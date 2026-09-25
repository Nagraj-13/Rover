# Rover Electrical & Circuit Documentation

This directory contains wiring schematics, pinout references, and electrical diagrams for the **Raspberry Pi 5 AI Rover**.

## Documentation Index

| Document | Description | Format |
| :--- | :--- | :--- |
| **[gpio_pinout.md](gpio_pinout.md)** | Full Raspberry Pi 5 40-pin GPIO mapping, physical pin numbers, and pin allocations. | ASCII / Markdown Table |
| **[motor_driver_wiring.md](motor_driver_wiring.md)** | Detailed wiring for dual IBT-2 (BTS7960) motor drivers, 4 DC motors, and logic pins. | ASCII & Mermaid |
| **[sensors_and_camera.md](sensors_and_camera.md)** | Pi Camera 3 CSI ribbon interface and VL53L0X Time-of-Flight I2C connection diagram. | ASCII & Mermaid |
| **[power_distribution.md](power_distribution.md)** | Dual-rail power architecture, battery connections, common ground rule, and fuse protection. | ASCII & Mermaid |

---

## High-Level Electrical Safety Rules

> [!CAUTION]
> **1. Common Ground Rule**
> The **negative terminal** of the 12V motor battery and the **GND pins** of the Raspberry Pi 5 **MUST** be connected together. Without a shared common reference ground, the PWM signals cannot complete their electrical circuit, resulting in erratic, uncontrolled motor spins.

> [!WARNING]
> **2. Never Power Motors from the Raspberry Pi**
> The Raspberry Pi's 5V and 3.3V header pins are designed strictly for low-power logic and sensors. Connecting DC motors directly to the Pi's power rails will cause voltage drops, SD card corruption, and permanent silicon damage. Motors must always be powered from a dedicated external battery (e.g. 12V Li-ion or LiFePO4).

> [!IMPORTANT]
> **3. Over-Current Fuse Protection**
> The IBT-2 driver can deliver high peak current (up to 43A stall). Always place an inline automotive fuse (10A to 15A recommended for standard 12V geared DC motors) on the positive lead of the motor battery.

---

## High-Level System Architecture Diagram

```mermaid
graph TD
    subgraph Power_Subsystem [Power Architecture]
        BAT[12V Motor Battery] -->|Inline Fuse 10A-15A| B_POS[12V Power Rail]
        BAT --> B_NEG[Common Ground Rail]
        PI_PWR[5V 5A USB-C Power Bank / Buck] --> PI_5[Raspberry Pi 5]
        PI_5 -.->|Pin 6/9/14/20 GND| B_NEG
    end

    subgraph Controller [Compute & Vision]
        PI_5
        CAM[Raspberry Pi Camera 3] -->|15-to-22 pin CSI Ribbon| PI_5
        TOF[VL53L0X Distance Sensor] -->|I2C1: SDA Pin 3, SCL Pin 5| PI_5
    end

    subgraph Left_Drive [Left Motor Subsystem]
        PI_5 -->|Pin 11 GPIO17 RPWM| IBT_L[Left IBT-2 Driver]
        PI_5 -->|Pin 12 GPIO18 LPWM| IBT_L
        PI_5 -->|Pin 2 5V VCC / EN| IBT_L
        B_POS -->|B+| IBT_L
        B_NEG -->|B-| IBT_L
        IBT_L -->|M+ / M-| M1[Front Left DC Motor]
        IBT_L -->|M+ / M-| M2[Rear Left DC Motor]
    end

    subgraph Right_Drive [Right Motor Subsystem]
        PI_5 -->|Pin 15 GPIO22 RPWM| IBT_R[Right IBT-2 Driver]
        PI_5 -->|Pin 16 GPIO23 LPWM| IBT_R
        PI_5 -->|Pin 4 5V VCC / EN| IBT_R
        B_POS -->|B+| IBT_R
        B_NEG -->|B-| IBT_R
        IBT_R -->|M+ / M-| M3[Front Right DC Motor]
        IBT_R -->|M+ / M-| M4[Rear Right DC Motor]
    end
```
