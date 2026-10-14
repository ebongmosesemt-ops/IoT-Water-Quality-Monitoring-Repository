# Node-RED flow: Owo River QC reference implementation

## Status
This is a **reconstructed reference flow**, not the original exported production Node-RED flow. It was created from the documented four-stage validation architecture, the released dataset schema, and the ESP32 firmware's Adafruit IO feed names.

## Input feeds
The firmware publishes six Adafruit IO feeds:
- `temperature`
- `tds`
- `ec`
- `do`
- `ph`
- `turbidity`

The MQTT input uses `YOUR_ADAFRUIT_USERNAME/feeds/+` and therefore requires the username to be replaced after import.

## What the flow does
1. Subscribes to the six parameter feeds.
2. Reconstructs a complete hourly record from the six feed messages.
3. Stage 1: physical range checks.
4. Stage 2: hourly rate-of-change checks.
5. Stage 3: TDS/EC consistency checks.
6. Stage 4: centred 25-observation (~24-hour span) 3-SD check.
7. Assigns `validation_flag` and `row_qc`.
8. Preserves `environmental_event` and `imperfection_type` fields when supplied by an upstream/manual adjudication source.
9. Writes a JSONL record to `data/live_qc_records.jsonl` and publishes the QC record to `owo-river/qc/record`.

## Important limitation
A centred 25-observation window requires 12 future observations before the centre observation can be classified. Consequently, Stage 4 is delayed by approximately 12 hours. This is mathematically consistent with the centred-window method but is not instantaneous.

The historical dataset's `environmental_event` and `imperfection_type` fields were partly based on contextual adjudication and event/maintenance information. The six water-quality feeds alone cannot recreate those labels. Do not claim that this reference flow exactly reproduces historical adjudication unless the corresponding event and maintenance inputs are connected.

## Import
Import `owo_river_validation_flow.json` into Node-RED. Then:
1. Open the MQTT broker configuration.
2. Enter the Adafruit IO username and key in Node-RED credentials.
3. Change the MQTT input topic from `YOUR_ADAFRUIT_USERNAME/feeds/+` to `<username>/feeds/+`.
4. Deploy.
5. Confirm all six feeds are arriving hourly.

For production use, prefer MQTT over TLS (port 8883) and use Node-RED's credential store rather than placing secrets in the flow JSON.

## Optional contextual input
Publish JSON objects to `owo-river/context/<event-type>` when external context is available, for example:
```json
{"created_at":"2026-07-25T15:00:00Z","rainfall_mm_hr":2.85,"environmental_event":true,"maintenance":false,"imperfection_type":null}
```
This allows the flow to retain the contextual distinction between a genuine environmental event and a sensor artefact. The historical study used external rainfall/event information and maintenance observations; the six water-quality feeds alone cannot reproduce those labels.

The flow can also publish QC metadata to Adafruit IO feeds named `validation_flag`, `row_qc`, `environmental_event`, `imperfection_type`, `flag_reason`, `rainfall_mm_hr`, and `maintenance`. Create these feeds first if they are not already present.

## Optional contextual input
Publish JSON objects to `owo-river/context/<event-type>` when external context is available, for example:
```json
{"created_at":"2026-07-25T15:00:00Z","rainfall_mm_hr":2.85,"environmental_event":true,"maintenance":false,"imperfection_type":null}
```
This allows the flow to retain the contextual distinction between a genuine environmental event and a sensor artefact. The historical study used external rainfall/event information and maintenance observations; the six water-quality feeds alone cannot reproduce those labels.

The flow can also publish QC metadata to Adafruit IO feeds named `validation_flag`, `row_qc`, `environmental_event`, `imperfection_type`, `flag_reason`, `rainfall_mm_hr`, and `maintenance`. Create these feeds first if they are not already present.
