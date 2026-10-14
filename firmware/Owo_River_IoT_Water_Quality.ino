/*
 * Owo River IoT Water-Quality Monitoring System
 * Firmware implementation
 *
 * Embedded platform: ESP32-WROOM-32
 * Acquisition interval: 1 hour
 * Cloud transport: MQTT
 * Local persistence: SPIFFS, 128-record circular buffer
 *
 * Sensors:
 *   Atlas Scientific EZO-pH
 *   Atlas Scientific EZO-DO
 *   Atlas Scientific EZO-EC
 *   Dallas DS18B20
 *   TS-300B turbidity sensor
 *
 * Configure credentials and the TS-300B calibration coefficients before use.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <SPIFFS.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <LiquidCrystal_I2C.h>
#include <time.h>

// --------------------------- User configuration ---------------------------
#define WIFI_SSID       "CHANGE_WIFI_SSID"
#define WIFI_PASSWORD   "CHANGE_WIFI_PASSWORD"
#define AIO_USERNAME    "CHANGE_AIO_USERNAME"
#define AIO_KEY         "CHANGE_AIO_KEY"
#define MQTT_SERVER     "io.adafruit.com"
#define MQTT_PORT       1883
#define MQTT_FEED       "water_quality"

// EZO I2C addresses: pH=0x63, DO=0x61, EC=0x64.
#define EZO_PH_ADDR     0x63
#define EZO_DO_ADDR     0x61
#define EZO_EC_ADDR     0x64

#define DS18B20_PIN     4
#define TURBIDITY_PIN   33
#define LCD_ADDRESS     0x27
#define BUFFER_CAPACITY 128
#define ACQUISITION_MS  3600000UL

// TS-300B polynomial: NTU = A*V^2 + B*V + C.
// Replace these coefficients with the validated field calibration curve.
#define TURBIDITY_A     0.0f
#define TURBIDITY_B     0.0f
#define TURBIDITY_C     0.0f
#define ADC_VREF        3.3f
#define ADC_MAX         4095.0f

#define NTP_SERVER_1    "pool.ntp.org"
#define NTP_SERVER_2    "time.nist.gov"
#define GMT_OFFSET_SEC  3600
#define DST_OFFSET_SEC  0

// ------------------------------- Globals ---------------------------------
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
Preferences preferences;
OneWire oneWire(DS18B20_PIN);
DallasTemperature temperatureSensor(&oneWire);
LiquidCrystal_I2C lcd(LCD_ADDRESS, 16, 2);

SemaphoreHandle_t bufferMutex;
TaskHandle_t acquisitionTaskHandle = nullptr;
TaskHandle_t communicationTaskHandle = nullptr;

struct Measurement {
  char timestamp[25];
  float ph;
  float doMgL;
  float temperatureC;
  float ecUsCm;
  float tdsMgL;
  float turbidityNtu;
};

volatile bool newMeasurementAvailable = false;
Measurement latestMeasurement;

uint16_t bufferHead = 0;
uint16_t bufferTail = 0;
uint16_t bufferCount = 0;

// --------------------------- Utility functions ---------------------------
String slotPath(uint16_t slot) {
  char path[24];
  snprintf(path, sizeof(path), "/buffer/%03u.json", slot);
  return String(path);
}

void saveBufferState() {
  preferences.putUShort("head", bufferHead);
  preferences.putUShort("tail", bufferTail);
  preferences.putUShort("count", bufferCount);
}

void loadBufferState() {
  bufferHead = preferences.getUShort("head", 0);
  bufferTail = preferences.getUShort("tail", 0);
  bufferCount = preferences.getUShort("count", 0);
  if (bufferHead >= BUFFER_CAPACITY || bufferTail >= BUFFER_CAPACITY || bufferCount > BUFFER_CAPACITY) {
    bufferHead = bufferTail = bufferCount = 0;
    saveBufferState();
  }
}

bool getTimestamp(char *out, size_t len) {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo, 3000)) return false;
  strftime(out, len, "%Y-%m-%dT%H:%M:%S%z", &timeinfo);
  return true;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000UL) {
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

void connectMQTT() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  String clientId = String("owo-water-") + String((uint32_t)ESP.getEfuseMac(), HEX);
  String user = String(AIO_USERNAME);
  String topic = String(AIO_USERNAME) + "/feeds/" + MQTT_FEED;
  mqtt.setBufferSize(1024);
  mqtt.connect(clientId.c_str(), AIO_USERNAME, AIO_KEY);
  (void)topic;
}

bool ezoRead(uint8_t address, float &value) {
  Wire.beginTransmission(address);
  Wire.write('R');
  if (Wire.endTransmission() != 0) return false;
  vTaskDelay(pdMS_TO_TICKS(900));

  Wire.requestFrom((int)address, 32);
  if (Wire.available() < 2) return false;
  uint8_t status = Wire.read();
  if (status != 1) return false;

  char response[31];
  size_t i = 0;
  while (Wire.available() && i < sizeof(response) - 1) response[i++] = (char)Wire.read();
  response[i] = '\0';

  char *endPtr = nullptr;
  float parsed = strtof(response, &endPtr);
  if (endPtr == response) return false;
  value = parsed;
  return isfinite(value);
}

float readTemperatureC() {
  temperatureSensor.requestTemperatures();
  float t = temperatureSensor.getTempCByIndex(0);
  return (t == DEVICE_DISCONNECTED_C) ? NAN : t;
}

float readTurbidityNtu() {
  uint32_t sum = 0;
  const uint8_t samples = 20;
  for (uint8_t i = 0; i < samples; ++i) {
    sum += analogRead(TURBIDITY_PIN);
    vTaskDelay(pdMS_TO_TICKS(5));
  }
  float adc = sum / (float)samples;
  float voltage = (adc / ADC_MAX) * ADC_VREF;
  float ntu = TURBIDITY_A * voltage * voltage + TURBIDITY_B * voltage + TURBIDITY_C;
  if (!isfinite(ntu)) return NAN;
  return max(0.0f, ntu);
}

bool readMeasurement(Measurement &m) {
  if (!getTimestamp(m.timestamp, sizeof(m.timestamp))) return false;

  float ph, dissolvedOxygen, ec, temp;
  if (!ezoRead(EZO_PH_ADDR, ph)) return false;
  if (!ezoRead(EZO_DO_ADDR, dissolvedOxygen)) return false;
  if (!ezoRead(EZO_EC_ADDR, ec)) return false;
  temp = readTemperatureC();
  float turbidity = readTurbidityNtu();

  if (!isfinite(temp) || !isfinite(turbidity)) return false;

  m.ph = ph;
  m.doMgL = dissolvedOxygen;
  m.temperatureC = temp;
  m.ecUsCm = ec;
  m.tdsMgL = ec * 0.5f;
  m.turbidityNtu = turbidity;
  return true;
}

String measurementJson(const Measurement &m) {
  StaticJsonDocument<768> doc;
  doc["timestamp"] = m.timestamp;
  doc["pH"] = m.ph;
  doc["do_mg_l"] = m.doMgL;
  doc["temperature_c"] = m.temperatureC;
  doc["ec_us_cm"] = m.ecUsCm;
  doc["tds_mg_l"] = m.tdsMgL;
  doc["turbidity_ntu"] = m.turbidityNtu;
  doc["source"] = "ESP32";
  String payload;
  serializeJson(doc, payload);
  return payload;
}

bool enqueueMeasurement(const Measurement &m) {
  if (xSemaphoreTake(bufferMutex, pdMS_TO_TICKS(2000)) != pdTRUE) return false;

  String path = slotPath(bufferHead);
  File file = SPIFFS.open(path, FILE_WRITE);
  if (!file) {
    xSemaphoreGive(bufferMutex);
    return false;
  }
  String payload = measurementJson(m);
  size_t written = file.print(payload);
  file.close();

  if (written != payload.length()) {
    SPIFFS.remove(path);
    xSemaphoreGive(bufferMutex);
    return false;
  }

  bufferHead = (bufferHead + 1) % BUFFER_CAPACITY;
  if (bufferCount < BUFFER_CAPACITY) {
    bufferCount++;
  } else {
    // Circular buffer: discard the oldest unsent record when capacity is reached.
    SPIFFS.remove(slotPath(bufferTail));
    bufferTail = (bufferTail + 1) % BUFFER_CAPACITY;
  }
  saveBufferState();
  xSemaphoreGive(bufferMutex);
  return true;
}

bool publishOldestBuffered() {
  if (!mqtt.connected()) return false;
  if (xSemaphoreTake(bufferMutex, pdMS_TO_TICKS(2000)) != pdTRUE) return false;
  if (bufferCount == 0) {
    xSemaphoreGive(bufferMutex);
    return false;
  }

  String path = slotPath(bufferTail);
  File file = SPIFFS.open(path, FILE_READ);
  if (!file) {
    SPIFFS.remove(path);
    bufferTail = (bufferTail + 1) % BUFFER_CAPACITY;
    bufferCount--;
    saveBufferState();
    xSemaphoreGive(bufferMutex);
    return true;
  }

  String payload = file.readString();
  file.close();

  String topic = String(AIO_USERNAME) + "/feeds/" + MQTT_FEED;
  bool accepted = mqtt.publish(topic.c_str(), payload.c_str(), true);
  if (accepted) {
    SPIFFS.remove(path);
    bufferTail = (bufferTail + 1) % BUFFER_CAPACITY;
    bufferCount--;
    saveBufferState();
  }

  xSemaphoreGive(bufferMutex);
  return accepted;
}

void updateLCD(const Measurement &m) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("pH:"); lcd.print(m.ph, 2);
  lcd.print(" DO:"); lcd.print(m.doMgL, 1);
  lcd.setCursor(0, 1);
  lcd.print("T:"); lcd.print(m.temperatureC, 1);
  lcd.print(" Tu:"); lcd.print(m.turbidityNtu, 0);
}

// ------------------------------- Tasks -----------------------------------
void acquisitionTask(void *parameter) {
  (void)parameter;
  TickType_t lastWake = xTaskGetTickCount();

  for (;;) {
    Measurement m;
    if (readMeasurement(m)) {
      if (xSemaphoreTake(bufferMutex, pdMS_TO_TICKS(1000)) == pdTRUE) {
        latestMeasurement = m;
        newMeasurementAvailable = true;
        xSemaphoreGive(bufferMutex);
      }
      updateLCD(m);
      enqueueMeasurement(m);
    }

    vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(ACQUISITION_MS));
  }
}

void communicationTask(void *parameter) {
  (void)parameter;
  for (;;) {
    connectWiFi();
    if (WiFi.status() == WL_CONNECTED) {
      mqtt.loop();
      connectMQTT();
      mqtt.loop();
      for (uint8_t i = 0; i < 4 && bufferCount > 0 && mqtt.connected(); ++i) {
        if (!publishOldestBuffered()) break;
        mqtt.loop();
      }
    }
    vTaskDelay(pdMS_TO_TICKS(5000));
  }
}

// -------------------------------- Setup ----------------------------------
void setup() {
  Serial.begin(115200);
  Wire.begin();
  analogReadResolution(12);

  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Owo Water IoT");
  lcd.setCursor(0, 1);
  lcd.print("Starting...");

  temperatureSensor.begin();

  if (!SPIFFS.begin(true)) {
    Serial.println("SPIFFS mount failed");
  } else {
    if (!SPIFFS.exists("/buffer")) SPIFFS.mkdir("/buffer");
  }

  preferences.begin("buffer", false);
  loadBufferState();

  bufferMutex = xSemaphoreCreateMutex();
  if (!bufferMutex) {
    Serial.println("Mutex creation failed");
    while (true) vTaskDelay(pdMS_TO_TICKS(1000));
  }

  connectWiFi();
  configTime(GMT_OFFSET_SEC, DST_OFFSET_SEC, NTP_SERVER_1, NTP_SERVER_2);
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setKeepAlive(60);
  mqtt.setBufferSize(1024);

  // Acquisition on core 0; communications on core 1.
  xTaskCreatePinnedToCore(acquisitionTask, "acquisition", 8192, nullptr, 2, &acquisitionTaskHandle, 0);
  xTaskCreatePinnedToCore(communicationTask, "communication", 8192, nullptr, 1, &communicationTaskHandle, 1);
}

void loop() {
  // Application work is performed by the two FreeRTOS tasks.
  vTaskDelay(pdMS_TO_TICKS(1000));
}
