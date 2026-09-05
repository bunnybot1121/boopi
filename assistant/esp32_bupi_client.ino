#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>

// 1. REPLACE THESE WITH YOUR EXACT WIFI CREDENTIALS (2.4GHz ONLY)
const char* ssid = "home";
const char* password = "sachin1121";

// 2. BUPI PC SERVER SETTINGS (Pre-filled with your current local IP)
const char* websocket_server = "192.168.0.106";
const uint16_t websocket_port = 8767;

WebSocketsClient webSocket;
// Note: If your LCD remains blank or shows black boxes, change 0x27 to 0x3F
LiquidCrystal_I2C lcd(0x27, 16, 2); 

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Disconnected!");
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Bupi Offline...");
      break;
    case WStype_CONNECTED:
      Serial.println("[WS] Connected to Bupi!");
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Bupi Connected!");
      // Send capability announcement to Bupi Hub
      webSocket.sendTXT("{\"type\":\"announce\",\"device\":\"LCD Display (WS)\",\"capabilities\":[\"Display\"],\"tasks\":[\"Displaying Bupi Status/Reminders\"]}");
      break;
    case WStype_TEXT: {
      // Parse JSON from Python
      StaticJsonDocument<200> doc;
      DeserializationError error = deserializeJson(doc, payload);
      
      if (!error) {
        const char* title = doc["title"];
        const char* message = doc["message"];
        
        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print(title);
        lcd.setCursor(0, 1);
        lcd.print(message);
      }
      break;
    }
  }
}

void setup() {
  Serial.begin(115200);
  
  // Initialize LCD
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Booting...");
  
  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  Serial.println("Scanning WiFi...");
  lcd.setCursor(0, 1);
  lcd.print("Scanning WiFi...");
  
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println("\nWiFi connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // Show successful WiFi connection
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("WiFi Connected!");
  lcd.setCursor(0, 1);
  lcd.print(WiFi.localIP().toString());
  delay(2000);

  // Connect to Bupi's WebSocket Server
  webSocket.begin(websocket_server, websocket_port, "/");
  webSocket.onEvent(webSocketEvent);
  
  // Try to reconnect every 5 seconds if connection drops
  webSocket.setReconnectInterval(5000);
  
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Connecting to");
  lcd.setCursor(0, 1);
  lcd.print("Bupi Hub...");
}

void loop() {
  webSocket.loop();
}
