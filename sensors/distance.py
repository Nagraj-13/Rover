"""
EdgeRover — VL53L0X Time-of-Flight (ToF) Laser Distance Sensor Driver.
Interfaced via I2C1 (GPIO2 SDA, GPIO3 SCL) on Raspberry Pi 5.

Features:
- Thread-safe continuous distance polling (30 Hz).
- Hardware proximity safety interlock (<30cm obstacle detection).
- Automatic I2C bus discovery with graceful fallback to simulation on development laptops.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Optional

logger = logging.getLogger("RoverDistanceSensor")

# Check for hardware I2C libraries
try:
    import board
    import busio
    import adafruit_vl53l0x
    VL53L0X_HARDWARE_AVAILABLE = True
except ImportError:
    VL53L0X_HARDWARE_AVAILABLE = False


class DistanceSensor:
    """
    Asynchronous driver for the VL53L0X Time-of-Flight Laser Distance Sensor.
    """

    DEFAULT_I2C_ADDRESS = 0x29
    SAFETY_THRESHOLD_CM = 30.0

    def __init__(
        self,
        i2c_bus: int = 1,
        address: int = DEFAULT_I2C_ADDRESS,
        safety_threshold_cm: float = SAFETY_THRESHOLD_CM,
        poll_interval_s: float = 0.033,  # ~30 Hz
        simulate: bool = False,
    ):
        self.i2c_bus_num = i2c_bus
        self.address = address
        self.safety_threshold_cm = safety_threshold_cm
        self.poll_interval_s = poll_interval_s
        self.simulate = simulate or not VL53L0X_HARDWARE_AVAILABLE

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._current_distance_cm: float = 120.0
        self._last_read_time: float = 0.0
        self._sensor_initialized: bool = False
        self._sensor_hw = None
        self._poll_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Initialize the sensor and start background polling."""
        if self._poll_thread and self._poll_thread.is_alive():
            return

        self._stop_event.clear()
        self._init_sensor()

        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="VL53L0XPoller",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("DistanceSensor poller started.")

    def stop(self) -> None:
        """Stop background distance polling."""
        self._stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.5)
        logger.info("DistanceSensor poller stopped.")

    def _init_sensor(self) -> bool:
        """Attempt hardware I2C connection to VL53L0X."""
        if self.simulate:
            logger.info("DistanceSensor running in simulation mode.")
            self._sensor_initialized = True
            return True

        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self._sensor_hw = adafruit_vl53l0x.VL53L0X(i2c, address=self.address)
            # Optimize timing budget for fast obstacle avoidance (20ms)
            self._sensor_hw.measurement_timing_budget = 20000
            self._sensor_initialized = True
            logger.info(f"VL53L0X hardware sensor initialized at I2C address 0x{self.address:02x}.")
            return True
        except Exception as e:
            logger.warning(f"Could not initialize VL53L0X hardware ({e}). Falling back to simulation.")
            self.simulate = True
            self._sensor_initialized = True
            return False

    def _poll_loop(self) -> None:
        """Continuous background thread polling distance values."""
        while not self._stop_event.is_set():
            t_now = time.monotonic()

            if self.simulate:
                # Simulated smooth distance variation (60cm to 180cm)
                sim_dist = 120.0 + 50.0 * math.sin(t_now * 0.4)
                with self._lock:
                    self._current_distance_cm = round(sim_dist, 1)
                    self._last_read_time = t_now
            else:
                try:
                    if self._sensor_hw:
                        # Sensor returns distance in millimeters
                        dist_mm = self._sensor_hw.range
                        if dist_mm and dist_mm < 8190:  # 8190 is out of range indicator
                            with self._lock:
                                self._current_distance_cm = round(dist_mm / 10.0, 1)
                                self._last_read_time = t_now
                except Exception as e:
                    logger.debug(f"I2C read transient error: {e}")

            time.sleep(self.poll_interval_s)

    def get_distance_cm(self) -> float:
        """Retrieve the latest distance measurement in centimeters."""
        with self._lock:
            return self._current_distance_cm

    def is_obstacle_close(self, threshold_cm: Optional[float] = None) -> bool:
        """
        Check if an obstacle is within the safety threshold.
        Used by the safety controller to prevent forward motion.
        """
        cutoff = threshold_cm if threshold_cm is not None else self.safety_threshold_cm
        return self.get_distance_cm() < cutoff

    def get_status(self) -> dict:
        """Retrieve distance sensor health and status telemetry."""
        with self._lock:
            dist = self._current_distance_cm
            return {
                "distance_cm": dist,
                "obstacle_detected": dist < self.safety_threshold_cm,
                "safety_threshold_cm": self.safety_threshold_cm,
                "simulated": self.simulate,
                "hardware_available": VL53L0X_HARDWARE_AVAILABLE,
                "timestamp": self._last_read_time,
            }
