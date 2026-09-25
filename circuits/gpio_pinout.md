# Raspberry Pi 5 40-Pin GPIO Header Mapping

The table below describes all 40 pins on the Raspberry Pi 5 header.
Pins utilized by the **Rover Project** are highlighted with their designated hardware functions.

---

## Visual Pin Header (ASCII)

```text
                             Raspberry Pi 5 GPIO Header
                                     (Top View)
                           3.3V Power  [ 1] [ 2]  5V Power (To Left IBT-2 VCC & EN)
         VL53L0X SDA (GPIO 2 / I2C1)  [ 3] [ 4]  5V Power (To Right IBT-2 VCC & EN)
         VL53L0X SCL (GPIO 3 / I2C1)  [ 5] [ 6]  Ground (Common Reference)
                             GPIO 4   [ 7] [ 8]  GPIO 14 (UART TX)
                             Ground   [ 9] [10]  GPIO 15 (UART RX)
          Left Motor RPWM (GPIO 17)   [11] [12]  Left Motor LPWM (GPIO 18 / PWM0)
                             GPIO 27  [13] [14]  Ground (Common Reference)
         Right Motor RPWM (GPIO 22)   [15] [16]  Right Motor LPWM (GPIO 23)
                           3.3V Power [17] [18]  GPIO 24
                             GPIO 10  [19] [20]  Ground
                             GPIO 9   [21] [22]  GPIO 25
                             GPIO 11  [23] [24]  GPIO 8
                             Ground   [25] [26]  GPIO 7
                             GPIO 0   [27] [28]  GPIO 1
                             GPIO 5   [29] [30]  Ground
                             GPIO 6   [31] [32]  GPIO 12 (PWM0)
                             GPIO 13  [33] [34]  Ground
                             GPIO 19  [35] [36]  GPIO 16
                             GPIO 26  [37] [38]  GPIO 20
                             Ground   [39] [40]  GPIO 21
```

---

## Detailed Pinout Table

| Physical Pin | Header Label / BCM | Default Function | Rover Designation | Connected Module & Notes |
| :---: | :---: | :---: | :---: | :--- |
| **Pin 1** | **3V3 Power** | 3.3V DC Power | **3.3V Logic Supply** | Powers VL53L0X VCC (if 3.3V model) |
| **Pin 2** | **5V Power** | 5.0V DC Power | **5V Logic Supply** | Powers Left IBT-2 VCC, R_EN, L_EN |
| **Pin 3** | **GPIO 2** | I2C1 SDA | **I2C1 Data** | Connected to VL53L0X SDA |
| **Pin 4** | **5V Power** | 5.0V DC Power | **5V Logic Supply** | Powers Right IBT-2 VCC, R_EN, L_EN |
| **Pin 5** | **GPIO 3** | I2C1 SCL | **I2C1 Clock** | Connected to VL53L0X SCL |
| **Pin 6** | **Ground** | 0V | **System GND** | Connected to Common Ground / Battery Negative |
| Pin 7 | GPIO 4 | GPCLK0 | Unused | Available |
| Pin 8 | GPIO 14 | UART0 TXD | Unused | Serial console TX |
| **Pin 9** | **Ground** | 0V | **System GND** | Connected to VL53L0X GND |
| Pin 10 | GPIO 15 | UART0 RXD | Unused | Serial console RX |
| **Pin 11** | **GPIO 17** | General I/O | **Left RPWM** | Forward PWM signal to Left IBT-2 |
| **Pin 12** | **GPIO 18** | PWM0 | **Left LPWM** | Reverse PWM signal to Left IBT-2 |
| Pin 13 | GPIO 27 | General I/O | Unused | Available |
| **Pin 14** | **Ground** | 0V | **System GND** | Common Ground to Left IBT-2 Logic GND |
| **Pin 15** | **GPIO 22** | General I/O | **Right RPWM** | Forward PWM signal to Right IBT-2 |
| **Pin 16** | **GPIO 23** | General I/O | **Right LPWM** | Reverse PWM signal to Right IBT-2 |
| Pin 17 | 3V3 Power | 3.3V DC Power | Unused | 3.3V power |
| Pin 18 | GPIO 24 | General I/O | Unused | Available (Reserved for VL53L0X XSHUT) |
| Pin 19 | GPIO 10 | SPI0 MOSI | Unused | Available |
| **Pin 20** | **Ground** | 0V | **System GND** | Common Ground to Right IBT-2 Logic GND |
| Pin 21 | GPIO 9 | SPI0 MISO | Unused | Available |
| Pin 22 | GPIO 25 | General I/O | Unused | Available |
| Pin 23 | GPIO 11 | SPI0 SCLK | Unused | Available |
| Pin 24 | GPIO 8 | SPI0 CE0 | Unused | Available |
| Pin 25 | Ground | 0V | Unused | Ground |
| Pin 26 | GPIO 7 | SPI0 CE1 | Unused | Available |
| Pin 27 | GPIO 0 | ID_SD (EEPROM) | Reserved | Reserved for HAT ID |
| Pin 28 | GPIO 1 | ID_SC (EEPROM) | Reserved | Reserved for HAT ID |
| Pin 29 | GPIO 5 | General I/O | Unused | Available |
| Pin 30 | Ground | 0V | Unused | Ground |
| Pin 31 | GPIO 6 | General I/O | Unused | Available |
| Pin 32 | GPIO 12 | PWM0 | Unused | Hardware PWM0 |
| Pin 33 | GPIO 13 | PWM1 | Unused | Hardware PWM1 |
| Pin 34 | Ground | 0V | Unused | Ground |
| Pin 35 | GPIO 19 | PWM1 | Unused | Hardware PWM1 |
| Pin 36 | GPIO 16 | General I/O | Unused | Available |
| Pin 37 | GPIO 26 | General I/O | Unused | Available |
| Pin 38 | GPIO 20 | General I/O | Unused | Available |
| Pin 39 | Ground | 0V | Unused | Ground |
| Pin 40 | GPIO 21 | General I/O | Unused | Available |

---

## Critical Software vs Physical Pin Distinction

In Python using `gpiozero`:

```python
# Use BCM GPIO numbers, NEVER physical header pin numbers!
left_motor = Motor(forward=17, backward=18, pwm=True)   # Physical Pin 11 & 12
right_motor = Motor(forward=22, backward=23, pwm=True)  # Physical Pin 15 & 16
```
