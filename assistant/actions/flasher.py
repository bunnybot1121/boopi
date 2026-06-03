import os
import subprocess
import serial.tools.list_ports
import re

def get_esp32_port():
    """Tries to automatically detect the COM port of an ESP32."""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        desc = port.description.lower()
        # Common ESP32 USB-to-UART bridge chips
        if "cp210" in desc or "ch340" in desc or "ch9102" in desc or "uart" in desc:
            return port.device
    
    # Fallback: if there is only one port available, just guess it
    if len(ports) == 1:
        return ports[0].device
        
    return None

def auto_flash_code(cpp_code, progress_callback=None):
    """
    Compiles and flashes the C++ code to an ESP32.
    progress_callback(msg) is used to send UI updates.
    """
    from state_manager import state_mgr
    state_mgr.transition("drinking_coffee")
    
    def return_with_state(result_str, is_success=False):
        if is_success:
            state_mgr.transition("idle")
        else:
            state_mgr.transition("concerned")
        return result_str

    workspace_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace")
    project_dir = os.path.join(workspace_dir, "BupiNode")
    
    if not os.path.exists(project_dir):
        os.makedirs(project_dir)
        
    ino_file = os.path.join(project_dir, "BupiNode.ino")
    
    with open(ino_file, "w", encoding="utf-8") as f:
        f.write(cpp_code)
        
    if progress_callback:
        progress_callback("Compiling C++ code... (This may take a minute)")
        
    # Compile
    # Make sure ESP32 core is installed in arduino-cli: arduino-cli core install esp32:esp32
    compile_cmd = ["arduino-cli", "compile", "--fqbn", "esp32:esp32:esp32", project_dir]
    try:
        # Check if arduino-cli is installed
        subprocess.run(["arduino-cli", "version"], check=True, capture_output=True)
    except FileNotFoundError:
        return return_with_state("Error: arduino-cli is not installed or not in PATH. Please run 'winget install Arduino.ArduinoCLI'.", False)
        
    # Compile with real-time output reading
    compile_logs = []
    try:
        compile_proc = subprocess.Popen(compile_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, errors='ignore')
        for line in compile_proc.stdout:
            compile_logs.append(line)
            # Send specific compile status lines
            if "Sketch uses" in line or "Global variables" in line:
                if progress_callback:
                    progress_callback(line.strip())
        compile_proc.wait()
        if compile_proc.returncode != 0:
            return return_with_state(f"Error: Compilation failed.\n" + "".join(compile_logs), False)
    except Exception as e:
        return return_with_state(f"Error: Failed to run compiler: {e}", False)
        
    if progress_callback:
        progress_callback("Compiled successfully! Searching for ESP32...")
        
    port = get_esp32_port()
    if not port:
        return return_with_state("Error: Could not automatically detect ESP32 on any COM port. Is it plugged in?", False)
        
    if progress_callback:
        progress_callback(f"Found ESP32 on {port}! Uploading...")
        
    # Upload
    upload_cmd = ["arduino-cli", "upload", "-p", port, "--fqbn", "esp32:esp32:esp32", project_dir]
    upload_logs = []
    try:
        upload_proc = subprocess.Popen(upload_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, errors='ignore')
        
        # Read character-by-character to catch carriage returns (\r) esptool uses for progress updates
        buffer = []
        while True:
            char = upload_proc.stdout.read(1)
            if not char:
                break
            if char == '\n' or char == '\r':
                line = "".join(buffer).strip()
                buffer = []
                if line:
                    upload_logs.append(line + "\n")
                    # Parse percentage
                    pct_match = re.search(r'(\d+)\s*%', line)
                    if pct_match:
                        pct = pct_match.group(1)
                        if progress_callback:
                            progress_callback(f"Flashing to ESP32... {pct}%")
                    elif "Writing at" in line:
                        if progress_callback:
                            progress_callback(line)
            else:
                buffer.append(char)
        upload_proc.wait()
        if upload_proc.returncode != 0:
            return return_with_state(f"Error: Upload failed.\n" + "".join(upload_logs), False)
    except Exception as e:
        return return_with_state(f"Error: Failed to run uploader: {e}", False)
        
    if progress_callback:
        progress_callback("✅ Hardware Online! Successfully flashed to ESP32.")
        
    return return_with_state("SUCCESS", True)
