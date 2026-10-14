# Firmware Implementation

## Purpose

This firmware implements the embedded monitoring architecture developed for the Owo River IoT-based real-time water-quality monitoring system. It integrates sensor acquisition, local processing, wireless communication, cloud transmission, and field-operation support for continuous surface-water monitoring.

## System architecture

- Atlas Scientific EZO-pH / EZO-DO / EZO-EC
- DS18B20 water-temperature sensor
- TS-300B turbidity sensor
- ESP32 dual-core microcontroller
- FreeRTOS task-based operation
- Hourly water-quality data acquisition
- JSON-formatted measurement records
- MQTT communication to Adafruit IO
- SPIFFS-based 128-record circular transmission buffer
- LCD monitoring interface

## Measured parameters

- pH
- Dissolved oxygen (DO)
- Water temperature
- Electrical conductivity (EC)
- Total dissolved solids (TDS)
- Turbidity

## File

`Owo_River_IoT_Water_Quality.ino` is the definitive firmware implementation included with this repository.

## Data transmission

Sensor measurements are assembled into structured JSON records and placed in a local SPIFFS circular buffer. The communication task establishes Wi-Fi and MQTT connectivity and transmits buffered records to the configured Adafruit IO feed. Records remain locally stored until the MQTT client accepts the publication; the buffer provides resilience to temporary connectivity interruptions.

## Configuration before use

1. Set the Wi-Fi credentials.
2. Set the Adafruit IO username, key, MQTT server, and feed.
3. Verify the EZO I2C addresses and sensor configuration.
4. Replace the TS-300B voltage-to-NTU polynomial coefficients with the validated calibration curve for the installed sensor.
5. Confirm the ESP32 ADC reference and analogue input configuration.
6. Validate each sensor against the laboratory reference procedure before field deployment.

## Software requirements

The firmware requires the following Arduino libraries:

- PubSubClient
- ArduinoJson
- OneWire
- DallasTemperature
- LiquidCrystal_I2C

The ESP32 Arduino core provides Wi-Fi, Wire, SPIFFS, Preferences, and FreeRTOS support.

## Quality control

The firmware acquires and transmits measurements but does not assign the final `VALID`, `SUSPECT`, `ENVIRONMENTAL_EVENT`, or `INVALID_PARAMETER` classifications. Those classifications are generated downstream by the Node-RED/Python quality-control workflow documented elsewhere in this repository.
