/*
 * ZeroCloud Alpha_260409 - ESP32-C6 KIT Reference
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

// ---------------- Hardware ----------------
#define DHTPIN 4
#define DHTTYPE DHT11
#define I2C_SDA 6
#define I2C_SCL 7
#define BOOT_BTN 9

// ---------------- Project constants ----------------
static const char* BOOTSTRAP_POOL_ID = "POOL_ZC";
static const char* SKILL_LIST = "[\"SKILL_TEMP\",\"SKILL_HUM\",\"SKILL_DISPLAY\"]";

// Fill with your deployment values.
static const char* WIFI_SSID = "CHANGE_ME_WIFI_SSID";
static const char* WIFI_PASS = "CHANGE_ME_WIFI_PASS";
static const char* MQTT_BROKER = "192.168.1.10";

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
DHT dht(DHTPIN, DHTTYPE);
Adafruit_SSD1306 display(128, 64, &Wire, -1);
Preferences prefs;

String kitUID;
bool isProvisioned = false;
String poolID;
String gateID;
String kitID;

float currentTemp = 0.0f;
float currentHum = 0.0f;
unsigned long lastSensorMs = 0;
bool blinkState = false;

String overrideMsg = "";
unsigned long overrideEndMs = 0;

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

String skillTopic(const String& skillID) {
  return poolID + "/" + gateID + "/" + kitID + "/" + skillID;
}

void wipeProvisioning(const char* message) {
  prefs.begin("zc_arch", false);
  prefs.clear();
  prefs.end();

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(6, 28);
  display.print(message);
  display.display();
  delay(1500);
  ESP.restart();
}

void drawUI() {
  display.clearDisplay();
  if (millis() < overrideEndMs && overrideMsg.length() > 0) {
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
    display.print("[" + gateID + "] " + kitID);

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

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String topicStr = String(topic);
  String payloadStr;
  payloadStr.reserve(length);
  for (unsigned int i = 0; i < length; ++i) {
    payloadStr += static_cast<char>(payload[i]);
  }

  if (!isProvisioned && topicStr == (String(BOOTSTRAP_POOL_ID) + "/PROVISION/" + kitUID)) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payloadStr);
    if (err) {
      return;
    }

    prefs.begin("zc_arch", false);
    prefs.putString("pool", doc["pool_id"].as<String>());
    prefs.putString("gate", doc["gate_id"].as<String>());
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
  }

  if (isProvisioned && topicStr.endsWith("SYS/RESET")) {
    wipeProvisioning("REMOTE RESET");
  }

  if (isProvisioned && topicStr.endsWith("SKILL_DISPLAY/SET")) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payloadStr);
    if (err) {
      return;
    }
    overrideMsg = doc["msg"].as<String>();
    overrideEndMs = millis() + (doc.containsKey("duration") ? doc["duration"].as<int>() : 5000);
  }
}

void ensureMqttConnected() {
  if (mqttClient.connected()) {
    return;
  }

  mqttClient.setServer(MQTT_BROKER, 1883);
  if (!isProvisioned) {
    if (mqttClient.connect(kitUID.c_str())) {
      String pendingTopic = String(BOOTSTRAP_POOL_ID) + "/PENDING/" + kitUID;
      String provisionTopic = String(BOOTSTRAP_POOL_ID) + "/PROVISION/" + kitUID;
      String payload = "{\"skills\":" + String(SKILL_LIST) + "}";
      mqttClient.publish(pendingTopic.c_str(), payload.c_str());
      mqttClient.subscribe(provisionTopic.c_str());
    }
    return;
  }

  String statusTopic = skillTopic("STATUS");
  String lwtPayload = "{\"status\":\"OFFLINE\"}";
  if (mqttClient.connect(kitID.c_str(), "", "", statusTopic.c_str(), 1, true, lwtPayload.c_str())) {
    String onlinePayload = "{\"status\":\"ONLINE\",\"uid\":\"" + kitUID + "\",\"skills\":" + String(SKILL_LIST) + "}";
    mqttClient.publish(statusTopic.c_str(), onlinePayload.c_str(), true);
    mqttClient.subscribe((poolID + "/" + gateID + "/" + kitID + "/#").c_str());
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL);
  dht.begin();
  pinMode(BOOT_BTN, INPUT_PULLUP);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    for (;;) { delay(10); }
  }

  kitUID = generateUID();
  prefs.begin("zc_arch", true);
  isProvisioned = prefs.getBool("prov", false);
  if (isProvisioned) {
    poolID = prefs.getString("pool", "POOL_ZC");
    gateID = prefs.getString("gate", "GATE_01");
    kitID = prefs.getString("kit", "KIT_00001");
  }
  prefs.end();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  mqttClient.setCallback(mqttCallback);
}

void loop() {
  unsigned long now = millis();

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

  if (now - lastSensorMs > 3000) {
    lastSensorMs = now;
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h) && !isnan(t)) {
      currentHum = h;
      currentTemp = t;
      if (isProvisioned && mqttClient.connected()) {
        mqttClient.publish(skillTopic("SKILL_TEMP").c_str(), (String("{\"value\":") + String(currentTemp, 1) + "}").c_str());
        mqttClient.publish(skillTopic("SKILL_HUM").c_str(), (String("{\"value\":") + String(currentHum, 1) + "}").c_str());
      }
    }
  }
}
