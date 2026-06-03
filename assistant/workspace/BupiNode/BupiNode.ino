#include <WiFi.h>
#include <PubSubClient.h>

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Hardcoded Network Credentials (BUPI Rule 5)
const char* ssid = "home";
const char* password = "sachin1121";
const char* mqtt_server = "192.168.0.102";

// LCD Object (BUPI Rule 1 & Chapter A)
// Common addresses: 0x27, 0x3F. Using 0x27 as per user's original code.
LiquidCrystal_I2C lcd(0x27, 16, 2);

const int mq2Pin = 34; // Analog MQ2 gas sensor input pin

WiFiClient espClient;
PubSubClient client(espClient);

String clientId = "";

// Non-blocking timers (BUPI Rule 2)
unsigned long lastReconnectAttempt = 0;
const long reconnectInterval = 5000; // Attempt MQTT reconnect every 5 seconds

void callback(char* topic, byte* payload, unsigned int length) {
  // BUPI Rule 3: MQTT Actuator Logic for LCD
  // Chapter A: LiquidCrystal_I2C.h (LCD Displays)

  String payloadString = "";
  for (int i = 0; i < length; i++) {
    payloadString += (char)payload[i];
  }

  Serial.print("BUPI MQTT Message received on topic: ");
  Serial.println(topic);
  Serial.print("Payload: ");
  Serial.println(payloadString);

  lcd.clear();              // Clear the display
  lcd.setCursor(0,0);       // Set cursor to column 0, row 0
  lcd.print(payloadString); // Print the received payload string
}

void reconnectMQTT() {
  // BUPI Rule 2: Remove Blocking Code - non-blocking MQTT reconnect
  if (client.connected()) {
    return; // Already connected
  }

  unsigned long currentMillis = millis();
  if (currentMillis - lastReconnectAttempt > reconnectInterval) {
    lastReconnectAttempt = currentMillis; // Update the last attempt time
    Serial.print("Attempting MQTT connection...");
    
    if (clientId == "") {
      String mac = WiFi.macAddress();
      mac.replace(":", "");
      clientId = "BUPI_ESP32_MQ2_" + mac;
    }
    
    // Attempt to connect with a unique client ID
    if (client.connect(clientId.c_str())) { 
      Serial.println("connected");
      // BUPI Rule 3 & Chapter A: Subscribe to actuator topic for LCD
      client.subscribe("bupi/actuators/lcd/cmd");
      Serial.println("Subscribed to bupi/actuators/lcd/cmd");
      
      // Announcement
      String announce = "{\"device\":\"MQ2 Gas & LCD Display\",\"client_id\":\"" + clientId + "\",\"ip\":\"" + WiFi.localIP().toString() + "\",\"capabilities\":[\"Display\",\"Sensor\"],\"tasks\":[\"Displaying status\",\"Sensing gas concentration\"],\"status\":\"online\"}";
      client.publish("bupi/nodes/announce", announce.c_str());
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" trying again...");
    }
  }
}

void setup() {
  Serial.begin(115200);

  // Start WiFi connection (BUPI Rule 2: Non-blocking handled in loop)
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);
  // No blocking while loop here. WiFi connection status will be checked in loop().
  
  // Initialize MQTT Client
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  // Initialize I2C and LCD (BUPI Rule 1 & Chapter A)
  Wire.begin();       // Initialize I2C bus
  lcd.init();         // Initialize the LCD
  lcd.backlight();    // Turn on the backlight

  // Display initial message on LCD
  lcd.setCursor(0,0);
  lcd.print("BUPI LCD Node");
  lcd.setCursor(0,1);
  lcd.print("Waiting for Cmd");

  pinMode(mq2Pin, INPUT);
}

void loop() {
  // BUPI Rule 2: Remove Blocking Code - Non-blocking WiFi connection check
  if (WiFi.status() != WL_CONNECTED) {
    // If WiFi is not connected, print a dot periodically and wait.
    // WiFi.begin() in setup() asynchronously tries to connect.
    static unsigned long lastWifiStatusPrint = 0;
    if (millis() - lastWifiStatusPrint > 1000) { // Print dot every second
      Serial.print(".");
      lastWifiStatusPrint = millis();
    }
    return; // Do not proceed with MQTT until WiFi is connected
  }

  // If WiFi is connected, proceed with MQTT logic
  // Check and reconnect MQTT if necessary (non-blocking)
  if (!client.connected()) {
    reconnectMQTT();
  }
  
  // Call client.loop() regularly to process MQTT messages and maintain connection
  client.loop();

  // Send periodic presence heartbeat every 5 seconds
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 5000) {
    lastHeartbeat = millis();
    if (client.connected()) {
      String heartbeat = "{\"device\":\"MQ2 Gas & LCD Display\",\"client_id\":\"" + clientId + "\",\"ip\":\"" + WiFi.localIP().toString() + "\",\"capabilities\":[\"Display\",\"Sensor\"],\"tasks\":[\"Displaying status\",\"Sensing gas concentration\"],\"status\":\"online\"}";
      client.publish("bupi/nodes/heartbeat", heartbeat.c_str());
    }
  }

  // Publish MQ2 gas sensor readings every 2000ms (non-blocking)
  static unsigned long lastMQ2Publish = 0;
  if (millis() - lastMQ2Publish > 2000) {
    lastMQ2Publish = millis();
    if (client.connected()) {
      int sensorValue = analogRead(mq2Pin);
      String payload = "{\"value\":" + String(sensorValue) + ",\"lpg\":" + String(sensorValue) + "}";
      client.publish("bupi/sensors/mq2/state", payload.c_str());
    }
  }
}