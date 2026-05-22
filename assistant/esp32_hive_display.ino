#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// --- Configuration ---
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* mqtt_server = "192.168.0.101"; // IP of your PC running Mosquitto

// Initialize the LCD display
// The I2C address is usually 0x27 or 0x3F. 
// The dimensions are usually 16 columns and 2 rows (16, 2) or 20x4.
LiquidCrystal_I2C lcd(0x27, 16, 2);  

WiFiClient espClient;
PubSubClient client(espClient);

void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("Connecting to ");
  Serial.println(ssid);

  // Show Wi-Fi progress on the LCD
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Connecting WiFi");
  lcd.setCursor(0, 1);
  lcd.print(ssid);

  // Important for ESP32 stability
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);

  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    attempts++;
    // If it takes too long, print an error
    if (attempts == 20) {
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("WiFi Failed!");
      lcd.setCursor(0, 1);
      lcd.print("Check 2.4GHz");
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("WiFi Connected!");
    lcd.setCursor(0, 1);
    lcd.print(WiFi.localIP().toString());
    delay(2000);
    
    Serial.println("");
    Serial.println("WiFi connected");
    Serial.println("IP address: ");
    Serial.println(WiFi.localIP());
  }
}

String displayMessage = "";
bool newMsg = false;
unsigned long previousMillis = 0;
int scrollPos = 0;

void callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Message arrived [");
  Serial.print(topic);
  Serial.print("] ");
  
  displayMessage = "";
  for (int i = 0; i < length; i++) {
    displayMessage += (char)payload[i];
  }
  Serial.println(displayMessage);

  // Parse if there is a title (e.g. "Bupi Status: Listening...")
  String title = "Bupi Says:";
  String content = displayMessage;
  
  int colonIndex = displayMessage.indexOf(':');
  if (colonIndex > 0 && colonIndex < 16) {
      title = displayMessage.substring(0, colonIndex + 1);
      content = displayMessage.substring(colonIndex + 1);
      content.trim();
  } else {
      content = displayMessage;
  }
  
  displayMessage = content;

  // Display the title on the top row
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(title);
  
  newMsg = true;
  scrollPos = 0;
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Connecting to");
    lcd.setCursor(0, 1);
    lcd.print("Bupi Hub...");
    
    String clientId = "ESP32Client-";
    clientId += String(random(0xffff), HEX);
    
    if (client.connect(clientId.c_str())) {
      Serial.println("connected");
      
      // Subscribe to the specific topic for this Desk Display
      client.subscribe("bupi/nodes/desk_display/cmd");
      
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Desk Display");
      lcd.setCursor(0, 1);
      lcd.print("Online & Ready");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);

  // Initialize LCD display
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Booting Node...");

  setup_wifi();
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();
  
  // Non-blocking scroll logic
  if (displayMessage.length() > 0) {
    if (displayMessage.length() <= 16) {
      if (newMsg) {
        lcd.setCursor(0, 1);
        lcd.print(displayMessage);
        for(int i = displayMessage.length(); i < 16; i++) lcd.print(" ");
        newMsg = false;
      }
    } else {
      unsigned long currentMillis = millis();
      if (currentMillis - previousMillis >= 350) { // Scroll speed
        previousMillis = currentMillis;
        lcd.setCursor(0, 1);
        
        // Pad the message to loop it smoothly
        String paddedMsg = displayMessage + "                ";
        lcd.print(paddedMsg.substring(scrollPos, scrollPos + 16));
        
        scrollPos++;
        if (scrollPos > displayMessage.length() + 2) {
          scrollPos = 0; // Reset scroll
        }
      }
    }
  }
}
