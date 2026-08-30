import psutil
from logger import log

class SystemMonitorService:
  def __init__(self):
    pass

  def get_system_status(self) -> str:
    """Collects and returns system health metrics as a formatted string."""
    log.info("SystemMonitorService collecting metrics...")
    
    # 1. CPU Usage
    try:
      cpu_usage = psutil.cpu_percent(interval=0.1)
      cpu_count = psutil.cpu_count(logical=True)
      cpu_str = f"CPU Usage: {cpu_usage:.1f}% ({cpu_count} logical cores)"
    except Exception as e:
      cpu_str = "CPU Usage: Error retrieving stats"
      log.error(f"Failed to get CPU stats: {e}")

    # 2. RAM Usage
    try:
      mem = psutil.virtual_memory()
      mem_used_gb = mem.used / (1024 ** 3)
      mem_total_gb = mem.total / (1024 ** 3)
      mem_str = f"RAM Usage: {mem.percent:.1f}% ({mem_used_gb:.1f} GB of {mem_total_gb:.1f} GB used)"
    except Exception as e:
      mem_str = "RAM Usage: Error retrieving stats"
      log.error(f"Failed to get RAM stats: {e}")

    # 3. GPU Usage
    gpu_str = "GPU Usage: N/A"
    try:
      import GPUtil
      gpus = GPUtil.getGPUs()
      if gpus:
        gpu_lines = []
        for idx, gpu in enumerate(gpus):
          gpu_lines.append(
            f"GPU [{idx}] {gpu.name}:\n"
            f"  - Load: {gpu.load * 100:.1f}%\n"
            f"  - Memory: {gpu.memoryUtil * 100:.1f}% ({int(gpu.memoryUsed)}MB / {int(gpu.memoryTotal)}MB)"
          )
        gpu_str = "\n".join(gpu_lines)
      else:
        gpu_str = "GPU Usage: No dedicated GPUs detected"
    except ImportError:
      gpu_str = "GPU Usage: GPUtil library missing"
    except Exception as e:
      gpu_str = f"GPU Usage: Error retrieving stats ({e})"
      log.error(f"Failed to get GPU stats: {e}")

    # 4. Battery Status
    battery_str = "Battery: N/A"
    try:
      battery = psutil.sensors_battery()
      if battery:
        plugged = "Plugged in" if battery.power_plugged else "Discharging"
        secs_left = battery.secsleft
        if secs_left == psutil.POWER_TIME_UNLIMITED:
          time_str = " (Unlimited)"
        elif secs_left == psutil.POWER_TIME_UNKNOWN:
          time_str = " (Calculating time left...)"
        else:
          hrs = secs_left // 3600
          mins = (secs_left % 3600) // 60
          time_str = f" ({int(hrs)}h {int(mins)}m remaining)"
        battery_str = f"Battery: {battery.percent}% - {plugged}{time_str}"
      else:
        battery_str = "Battery: No battery detected (Desktop System)"
    except Exception as e:
      battery_str = f"Battery: Error retrieving stats ({e})"
      log.error(f"Failed to get battery stats: {e}")

    # 5. Temperature Status
    temp_str = "Temperature: N/A"
    try:
      temps = psutil.sensors_temperatures()
      if temps:
        temp_lines = []
        for name, entries in temps.items():
          for entry in entries:
            temp_lines.append(f"{name} {entry.label or ''}: {entry.current}°C")
        if temp_lines:
          temp_str = "Temperatures:\n" + "\n".join([f"  - {line}" for line in temp_lines])
        else:
          temp_str = "Temperatures: Sensors reported empty list"
      else:
        temp_str = "Temperatures: Sensor data not available on this platform"
    except AttributeError:
      temp_str = "Temperatures: Sensor access not supported on this OS"
    except Exception as e:
      temp_str = f"Temperatures: Error retrieving stats ({e})"
      log.error(f"Failed to get temperature stats: {e}")

    # Format entire status card
    report = (
      f"SYSTEM HEALTH MONITOR STATUS\n"
      f"===========================\n\n"
      f"{cpu_str}\n"
      f"{mem_str}\n\n"
      f"{gpu_str}\n\n"
      f"{battery_str}\n\n"
      f"{temp_str}\n"
    )
    return report
