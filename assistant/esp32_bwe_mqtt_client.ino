// Low-latency Serial Baud Rate
const long BAUDRATE = 115200;

// Demo state variables
int servoAngle = 0;
int sweepDirection = 1;
unsigned long lastTelemetryTime = 0;
const unsigned long telemetryInterval = 500; // Sweep position every 500ms

void setup() {
  Serial.begin(BAUDRATE);
  while (!Serial) {
    ; // Wait for serial port to connect (needed for native USB port only)
  }
  
  // Status debug print - will be shown in bridge console
  Serial.println("ESP32 HIL Controller Booted. Awaiting BWE packets...");
  
  // Configure demo visual indicator LED
  pinMode(2, OUTPUT); // Built-in LED on ESP32
  digitalWrite(2, HIGH);
  delay(200);
  digitalWrite(2, LOW);
}

void loop() {
  // 1. Process incoming JSON packets from BWE Simulator (No-Library String Parsing)
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    
    if (input.length() > 0) {
      // Look for target Pin 34 in the JSON string segment
      if (input.indexOf("\"pin\":34") != -1 || input.indexOf("\"pin\": 34") != -1) {
        int valIdx = input.indexOf("\"val\":");
        if (valIdx != -1) {
          // Parse float value after the '"val":' substring
          String valStr = "";
          for (int i = valIdx + 6; i < input.length(); i++) {
            char c = input.charAt(i);
            if (c == ',' || c == '}' || c == ' ' || c == '\r') {
              break;
            }
            valStr += c;
          }
          
          float val = valStr.toFloat();
          
          // Flash board LED if virtual gas concentration is above a threshold voltage (e.g. 1.5V)
          if (val > 1.5) {
            digitalWrite(2, HIGH);
          } else {
            digitalWrite(2, LOW);
          }
          
          // Print success callback log to trigger low-latency bridge RTT timer
          Serial.print("SUCCESS: Received Virtual Pin 34 Voltage: ");
          Serial.print(val);
          Serial.println("V. Built-in LED state updated.");
        }
      }
    }
  }

  // 2. Simulate sweep actuator outputs sending back to Virtual Servo on Pin 18
  unsigned long now = millis();
  if (now - lastTelemetryTime >= telemetryInterval) {
    lastTelemetryTime = now;
    
    // Sweep virtual servo angle between 0 and 180 degrees
    servoAngle += (15 * sweepDirection);
    if (servoAngle >= 180) {
      servoAngle = 180;
      sweepDirection = -1;
    } else if (servoAngle <= 0) {
      servoAngle = 0;
      sweepDirection = 1;
    }
    
    // Write JSON packet directly to Serial to bypass ArduinoJson dependency
    Serial.print("{\"type\":\"pin_write\",\"pin\":18,\"val\":");
    Serial.print(servoAngle);
    Serial.println("}");
  }
}
