"""
Serial Port Manager for BUPI Sonar Vision Testbed.
Thread-safe with no-reset DTR/RTS mode for ESP32, active watchdog, and robust JSON extraction.
"""

import json
import re
import threading
import time
from typing import Callable, List, Optional
import serial
import serial.tools.list_ports

from .sonar_imaging_engine import SonarImagingEngine


class SerialManager:
    def __init__(self, engine: SonarImagingEngine, on_ping_callback: Optional[Callable] = None):
        self.engine = engine
        self.on_ping_callback = on_ping_callback

        self._lock = threading.Lock()
        self.ser: Optional[serial.Serial] = None
        self.current_port: Optional[str] = None
        self.baud_rate: int = 115200
        self.is_connected: bool = False
        self.is_port_busy: bool = False
        self.busy_port_name: Optional[str] = None
        self.packet_count: int = 0

        self._serial_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._reader_stop_event = threading.Event()

        self.manual_pacer_angle: float = 90.0
        self.prev_s_ang: float = 90.0
        self.sweep_dir: str = "STEADY"

        # Start background watchdog to auto-connect to ESP32
        self._start_watchdog()

    @staticmethod
    def list_ports() -> List[dict]:
        """List all available physical COM/serial ports."""
        try:
            ports = serial.tools.list_ports.comports()
            return [{"device": p.device, "description": p.description, "hwid": p.hwid} for p in ports]
        except Exception:
            return []

    def _start_watchdog(self):
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_loop(self):
        """Continuously probes for ESP32 and auto-connects the moment the port is freed."""
        while not self._stop_event.is_set():
            time.sleep(1.5)
            if self._stop_event.is_set():
                break

            with self._lock:
                if self.is_connected:
                    continue

                ports = self.list_ports()
                target_port = None

                for p in ports:
                    dev = p["device"]
                    desc = p.get("description", "").lower()
                    if dev == "COM3" or "cp210" in desc or "ch340" in desc or "uart" in desc or "usb" in desc:
                        target_port = dev
                        break

                if not target_port:
                    self.is_port_busy = False
                    self.busy_port_name = None
                    continue

            # Attempt connection outside lock to avoid lock inversion during I/O
            self.connect(target_port, self.baud_rate)

    def connect(self, port: str, baud: int = 115200) -> bool:
        """Connect to physical serial port with no-reset DTR/RTS flags for ESP32."""
        match = re.search(r"(COM\d+|/dev/tty\w+)", str(port), re.I)
        clean_port = match.group(1).upper() if match else str(port).strip()

        with self._lock:
            if self.is_connected and self.current_port == clean_port and self.baud_rate == baud:
                return True

            self._stop_reader_internal()
            self._reader_stop_event.clear()

            try:
                ser_obj = serial.Serial(
                    clean_port, baud,
                    timeout=0.2,
                    dsrdtr=False,
                    rtscts=False
                )
                try:
                    ser_obj.dtr = False
                    ser_obj.rts = False
                except Exception:
                    pass

                time.sleep(0.08)
                try:
                    ser_obj.reset_input_buffer()
                except Exception:
                    pass

                self.ser = ser_obj
                self.current_port = clean_port
                self.baud_rate = baud
                self.is_connected = True
                self.is_port_busy = False
                self.busy_port_name = None

                self._serial_thread = threading.Thread(
                    target=self._serial_reader_loop,
                    args=(ser_obj,),
                    daemon=True
                )
                self._serial_thread.start()
                return True
            except Exception as e:
                err_str = str(e).lower()
                if "access is denied" in err_str or "permission" in err_str:
                    self.is_port_busy = True
                    self.busy_port_name = clean_port
                else:
                    self.is_port_busy = False
                    self.busy_port_name = None
                self.is_connected = False
                self.current_port = None
                return False

    def disconnect(self):
        with self._lock:
            self._stop_reader_internal()
            self.is_connected = False
            self.current_port = None

    def _stop_reader_internal(self):
        """Internal helper to safely stop reader thread and close port handle."""
        self._reader_stop_event.set()
        if self._serial_thread and self._serial_thread.is_alive():
            if threading.current_thread() != self._serial_thread:
                self._serial_thread.join(timeout=0.3)
        self._serial_thread = None

        if self.ser:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None

    def stop_all(self):
        self._stop_event.set()
        with self._lock:
            self._stop_reader_internal()
            self.is_connected = False
            self.current_port = None

    def update_pacer_angle(self, angle_deg: float):
        self.manual_pacer_angle = max(0.0, min(180.0, angle_deg))

    def send_command(self, cmd: dict) -> bool:
        """Send a JSON command line to the connected ESP32."""
        with self._lock:
            if not self.ser or not self.ser.is_open or not self.is_connected:
                return False
            try:
                line = json.dumps(cmd) + "\n"
                self.ser.write(line.encode("utf-8"))
                self.ser.flush()
                return True
            except Exception:
                return False

    def _serial_reader_loop(self, ser_obj: serial.Serial):
        """Continuously reads real newline-delimited JSON packets from ESP32."""
        buffer = ""
        while not self._stop_event.is_set() and not self._reader_stop_event.is_set():
            try:
                if not ser_obj or not ser_obj.is_open:
                    break

                try:
                    waiting = ser_obj.in_waiting
                except Exception:
                    if not ser_obj.is_open:
                        break
                    time.sleep(0.05)
                    continue

                try:
                    chunk = ser_obj.read(waiting or 1).decode("utf-8", errors="ignore")
                except Exception:
                    if not ser_obj.is_open:
                        break
                    time.sleep(0.05)
                    continue

                if not chunk:
                    time.sleep(0.01)
                    continue

                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line_str = line.strip()
                    if not line_str:
                        continue

                    s_idx = line_str.find("{")
                    e_idx = line_str.rfind("}")
                    if s_idx == -1 or e_idx == -1 or e_idx <= s_idx:
                        continue

                    json_part = line_str[s_idx:e_idx + 1]
                    try:
                        packet = json.loads(json_part)
                    except Exception:
                        continue

                    # Dual-Sensor or Single-Sensor packet extraction
                    mode = packet.get("mode", "STACKED_3D")
                    ts = packet.get("ts", int(time.time() * 1000))
                    bot_id = packet.get("bot_id", "BUPI-01")
                    imu_present = bool(packet.get("imu", False))
                    yaw = packet.get("yaw")
                    pitch = packet.get("pitch")
                    safety_stop = int(packet.get("safety_stop", 0))

                    # Distances: d1 (low) & d2 (high)
                    if "d1_cm" in packet:
                        d1_cm = float(packet.get("d1_cm", 400.0))
                        d2_cm = float(packet.get("d2_cm", d1_cm))
                        valid1 = bool(packet.get("valid1", 0) == 1)
                        valid2 = bool(packet.get("valid2", 0) == 1)
                    else:
                        d1_cm = float(packet.get("d_cm", 400.0))
                        d2_cm = d1_cm
                        valid1 = bool(packet.get("valid", 0) == 1)
                        valid2 = valid1

                    # Angles: s1 & s2
                    if "s1_ang" in packet:
                        s1_ang = float(packet.get("s1_ang", 90.0))
                        s2_ang = float(packet.get("s2_ang", s1_ang))
                    else:
                        raw_s = packet.get("s_ang")
                        s1_ang = float(raw_s) if raw_s is not None else self.manual_pacer_angle
                        s2_ang = s1_ang

                    min_ang = float(packet.get("min_ang", 45.0))
                    max_ang = float(packet.get("max_ang", 135.0))

                    # Track sweep direction (Left-to-Right vs Right-to-Left)
                    if s1_ang > self.prev_s_ang:
                        self.sweep_dir = "SWEEPING LEFT <-"
                    elif s1_ang < self.prev_s_ang:
                        self.sweep_dir = "-> SWEEPING RIGHT"
                    self.prev_s_ang = s1_ang

                    # Angle Fusion: If IMU present, combine global heading with relative servo angle
                    if imu_present and yaw is not None:
                        eff_angle = (float(yaw) + (s1_ang - 90.0)) % 360.0
                        if eff_angle > 180.0:
                            eff_angle = 360.0 - eff_angle
                    else:
                        eff_angle = s1_ang

                    telemetry = self.engine.ingest_dual_ping(
                        theta_deg=eff_angle,
                        d1_cm=d1_cm,
                        d2_cm=d2_cm,
                        valid1=valid1,
                        valid2=valid2,
                        s1_ang=s1_ang,
                        s2_ang=s2_ang,
                        mode=mode,
                        timestamp_ms=ts,
                        safety_stop=safety_stop,
                        imu_detected=imu_present,
                        yaw=yaw,
                        pitch=pitch,
                        min_ang=min_ang,
                        max_ang=max_ang,
                        sweep_dir=self.sweep_dir,
                        bot_id=bot_id
                    )

                    self.packet_count += 1
                    if self.packet_count % 50 == 0:
                        print(f"[SERIAL->WS] Packet #{self.packet_count}: s1={s1_ang:.1f}°, d1={d1_cm:.1f}cm, d2={d2_cm:.1f}cm, valid1={1 if valid1 else 0}, valid2={1 if valid2 else 0}")

                    if self.on_ping_callback:
                        self.on_ping_callback(telemetry)

            except Exception as e:
                if not ser_obj.is_open or self._stop_event.is_set() or self._reader_stop_event.is_set():
                    break
                time.sleep(0.05)

        with self._lock:
            if self.ser is ser_obj:
                self.is_connected = False
                self.current_port = None
