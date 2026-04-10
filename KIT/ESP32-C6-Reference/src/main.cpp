/*
 * ZeroCloud Alpha_260410 - ESP32-C6 KIT Reference
 * Copyright (C) 2026 Lei Wu
 *
 * SPDX-License-Identifier: GPL-3.0-only
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "DHT.h"
#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_mac.h>

// ================= Hardware =================
#define DHTPIN 4
#define DHTTYPE DHT11
#define I2C_SDA 6
#define I2C_SCL 7
#define BOOT_BTN 9

// ================= Protocol constants =================
static const char* BOOTSTRAP_POOL_ID = "POOL_ZC";
static const char* SKILL_CAPABILITIES_JSON = R"([{"id":"SKILL_TEMP","io":"input"},{"id":"SKILL_HUM","io":"input"},{"id":"SKILL_DISPLAY","io":"output","actions":[{"name":"SET","params":[{"key":"msg","type":"string","required":true},{"key":"duration","type":"number","default":5000,"min":500,"max":60000}]}],"supports_duration":true}])";
static const char* SKILL_LEGACY_LIST_JSON = R"(["SKILL_TEMP","SKILL_HUM","SKILL_DISPLAY"])";

// ================= Deployment values =================
// Fill with your deployment values before flashing.
const char* WIFI_SSID = "CHANGE_ME_WIFI_SSID";
const char* WIFI_PASS = "CHANGE_ME_WIFI_PASSWORD";
const char* BROKER_IP = "CHANGE_ME_MQTT_HOST";

WiFiClient espClient;
PubSubClient mqttClient(espClient);
DHT dht(DHTPIN, DHTTYPE);
Adafruit_SSD1306 display(128, 64, &Wire, -1);
Preferences prefs;

String kitUID = "";
bool isProvisioned = false;
String poolID = "";
String poolName = "";
String gateID = "";
String gateName = "";
String kitID = "";

float currentTemp = 0.0f;
float currentHum = 0.0f;
unsigned long lastSensorTimeMs = 0;
bool blinkState = false;

String overrideMsg = "";
unsigned long overrideEndTimeMs = 0;

bool btnPressed = false;
unsigned long btnPressStartMs = 0;

String generateUID() {
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  char uid[17];
  snprintf(
    uid,
    sizeof(uid),
    "%02X%02X%02X%02X%02X%02X%02X%02X",
    mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], mac[0] ^ mac[5], mac[1] ^ mac[4]
  );
  return String(uid);
}

String statusTopic() {
  return poolID + "/" + gateID + "/" + kitID + "/STATUS";
}

String skillValueTopic(const String& skillID) {
  return poolID + "/" + gateID + "/" + kitID + "/" + skillID;
}

String profileAnnounceTopic() {
  return poolID + "/" + gateID + "/SYS_GATE/PROFILE/ANNOUNCE";
}

void wipeProvisioning(const char* message) {
  prefs.begin("zc_arch", false);
  prefs.clear();
  prefs.end();

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(8, 28);
  display.print(message);
  display.display();
  delay(1400);
  ESP.restart();
}

void drawUI() {
  display.clearDisplay();
  if (millis() < overrideEndTimeMs && overrideMsg.length() > 0) {
    if (blinkState) {
      display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
    }
    display.setTextColor(blinkState ? SSD1306_BLACK : SSD1306_WHITE);
    display.setTextSize(2);
    display.setCursor(5, 24);
    display.print(overrideMsg);
    display.display();
    return;
  }

  if (!isProvisioned) {
    if (blinkState) {
      display.fillRect(0, 0, 128, 16, SSD1306_WHITE);
    }
    display.setTextColor(blinkState ? SSD1306_BLACK : SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(5, 4);
    display.print("AWAITING ADOPTION");
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(2);
    display.setCursor(5, 28);
    display.print("UID");
    display.setTextSize(1);
    display.setCursor(5, 50);
    display.print(kitUID);
  } else {
    display.fillRect(0, 0, 128, 16, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
    display.setTextSize(1);
    display.setCursor(5, 4);
    display.print("[" + (gateName.length() ? gateName : gateID) + "] " + kitID);

    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(2);
    display.setCursor(5, 20);
    display.print("T:");
    display.print(currentTemp, 1);
    display.setCursor(5, 40);
    display.print("H:");
    display.print(currentHum, 1);
  }
  display.display();
}

void applyDisplayCommand(const String& payloadText) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, payloadText);
  if (err) {
    return;
  }
  overrideMsg = doc["msg"].as<String>();
  overrideEndTimeMs = millis() + (doc.containsKey("duration") ? doc["duration"].as<int>() : 5000);
}

void handleSkillCommand(const String& commandPath, const String& payloadText) {
  const int divider = commandPath.lastIndexOf('/');
  if (divider <= 0) {
    return;
  }
  const String skillID = commandPath.substring(0, divider);
  const String action = commandPath.substring(divider + 1);

  if (skillID == "SYS" && action == "RESET") {
    wipeProvisioning("REMOTE RESET");
    return;
  }

  if (skillID == "SKILL_DISPLAY" && action == "SET") {
    applyDisplayCommand(payloadText);
    return;
  }

  // For new output skills, append handler branches here.
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  const String topicText = String(topic);
  String payloadText;
  payloadText.reserve(length);
  for (unsigned int i = 0; i < length; ++i) {
    payloadText += static_cast<char>(payload[i]);
  }

  const String provisionTopic = String(BOOTSTRAP_POOL_ID) + "/PROVISION/" + kitUID;
  if (!isProvisioned && topicText == provisionTopic) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payloadText);
    if (err) {
      return;
    }
    prefs.begin("zc_arch", false);
    prefs.putString("pool", doc["pool_id"].as<String>());
    prefs.putString("pool_name", doc["pool_name"].as<String>());
    prefs.putString("gate", doc["gate_id"].as<String>());
    prefs.putString("gate_name", doc["gate_name"].as<String>());
    prefs.putString("kit", doc["kit_id"].as<String>());
    prefs.putBool("prov", true);
    prefs.end();

    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(10, 24);
    display.print("ADOPTED");
    display.display();
    delay(1200);
    ESP.restart();
    return;
  }

  if (!isProvisioned) {
    return;
  }

  if (topicText == profileAnnounceTopic()) {
    StaticJsonDocument<256> profileDoc;
    DeserializationError profileErr = deserializeJson(profileDoc, payloadText);
    if (profileErr) {
      return;
    }
    const String nextPoolName = String(profileDoc["pool_name"] | poolName);
    const String nextGateName = String(profileDoc["gate_name"] | gateName);
    if (
      (nextPoolName.length() && nextPoolName != poolName)
      || (nextGateName.length() && nextGateName != gateName)
    ) {
      poolName = nextPoolName.length() ? nextPoolName : poolID;
      gateName = nextGateName.length() ? nextGateName : gateID;
      prefs.begin("zc_arch", false);
      prefs.putString("pool_name", poolName);
      prefs.putString("gate_name", gateName);
      prefs.end();
    }
    return;
  }

  const String ownPrefix = poolID + "/" + gateID + "/" + kitID + "/";
  if (!topicText.startsWith(ownPrefix)) {
    return;
  }
  const String commandPath = topicText.substring(ownPrefix.length());
  handleSkillCommand(commandPath, payloadText);
}

void publishPending() {
  const String topic = String(BOOTSTRAP_POOL_ID) + "/PENDING/" + kitUID;
  const String payload =
    String("{\"uid\":\"") + kitUID + "\",\"protocol\":\"ZC_SKILL_CAP_V1\",\"skills\":" +
    String(SKILL_CAPABILITIES_JSON) + "}";
  if (!mqttClient.publish(topic.c_str(), payload.c_str(), false)) {
    const String fallback =
      String("{\"uid\":\"") + kitUID + "\",\"skills\":" + String(SKILL_LEGACY_LIST_JSON) + "}";
    mqttClient.publish(topic.c_str(), fallback.c_str(), false);
  }
}

void publishOnlineStatus() {
  const String payload =
    String("{\"status\":\"ONLINE\",\"uid\":\"") + kitUID +
    "\",\"protocol\":\"ZC_SKILL_CAP_V1\",\"skills\":" + String(SKILL_CAPABILITIES_JSON) + "}";
  if (!mqttClient.publish(statusTopic().c_str(), payload.c_str(), true)) {
    const String fallback =
      String("{\"status\":\"ONLINE\",\"uid\":\"") + kitUID +
      "\",\"skills\":" + String(SKILL_LEGACY_LIST_JSON) + "}";
    mqttClient.publish(statusTopic().c_str(), fallback.c_str(), true);
  }
}

void ensureMqttConnected() {
  if (mqttClient.connected()) {
    return;
  }

  mqttClient.setServer(BROKER_IP, 1883);

  if (!isProvisioned) {
    if (mqttClient.connect(kitUID.c_str())) {
      publishPending();
      mqttClient.subscribe((String(BOOTSTRAP_POOL_ID) + "/PROVISION/" + kitUID).c_str());
    }
    return;
  }

  const String lwtPayload = String("{\"status\":\"OFFLINE\",\"uid\":\"") + kitUID + "\"}";
  if (mqttClient.connect(
      kitID.c_str(),
      "",
      "",
      statusTopic().c_str(),
      1,
      true,
      lwtPayload.c_str()
  )) {
    publishOnlineStatus();
    mqttClient.subscribe((poolID + "/" + gateID + "/" + kitID + "/#").c_str());
    mqttClient.subscribe(profileAnnounceTopic().c_str());
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL);
  dht.begin();
  pinMode(BOOT_BTN, INPUT_PULLUP);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    for (;;) {
      delay(10);
    }
  }

  kitUID = generateUID();
  prefs.begin("zc_arch", true);
  isProvisioned = prefs.getBool("prov", false);
  if (isProvisioned) {
    poolID = prefs.getString("pool", "POOL_ZC");
    poolName = prefs.getString("pool_name", poolID);
    gateID = prefs.getString("gate", "GATE_01");
    gateName = prefs.getString("gate_name", gateID);
    kitID = prefs.getString("kit", "KIT_00001");
  }
  prefs.end();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  mqttClient.setBufferSize(768);
  mqttClient.setCallback(mqttCallback);
}

void loop() {
  const unsigned long now = millis();

  if (digitalRead(BOOT_BTN) == LOW) {
    if (!btnPressed) {
      btnPressed = true;
      btnPressStartMs = now;
    } else if (now - btnPressStartMs > 3000) {
      wipeProvisioning("LOCAL HARD RESET");
    }
  } else {
    btnPressed = false;
  }

  if (now % 400 < 20) {
    blinkState = !blinkState;
    drawUI();
    delay(20);
  }

  if (WiFi.status() == WL_CONNECTED) {
    ensureMqttConnected();
    mqttClient.loop();
  }

  if (now - lastSensorTimeMs > 3000) {
    lastSensorTimeMs = now;
    const float hum = dht.readHumidity();
    const float temp = dht.readTemperature();
    if (!isnan(hum) && !isnan(temp)) {
      currentHum = hum;
      currentTemp = temp;
      if (isProvisioned && mqttClient.connected()) {
        mqttClient.publish(
          skillValueTopic("SKILL_TEMP").c_str(),
          (String("{\"value\":") + String(currentTemp, 1) + "}").c_str()
        );
        mqttClient.publish(
          skillValueTopic("SKILL_HUM").c_str(),
          (String("{\"value\":") + String(currentHum, 1) + "}").c_str()
        );
      }
    }
  }
}
