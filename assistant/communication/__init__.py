"""
BUPI Communication Package
==========================
Simulation engine, physical ESP32 bridge, and WebSocket broadcast service.
"""

from .bridge import BupiBridge, ArenaSimulation, PhysicalESP32Connection

__all__ = ["BupiBridge", "ArenaSimulation", "PhysicalESP32Connection"]
