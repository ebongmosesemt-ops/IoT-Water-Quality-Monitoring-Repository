# Data dictionary

## Core telemetry
| Field | Meaning | Unit |
|---|---|---|
| `created_at` | UTC timestamp of the record | ISO 8601 |
| `value_ph` | Raw pH telemetry | pH |
| `value_temperature_c` | Raw temperature telemetry | °C |
| `value_turbidity_ntu` | Raw turbidity telemetry | NTU |
| `value_ec_uscm` | Raw electrical conductivity telemetry | µS/cm |
| `value_tds_mgl` | Raw total dissolved solids telemetry | mg/L |
| `value_do_mgl` | Raw dissolved oxygen telemetry | mg/L |

## Quality-control metadata
| Field | Meaning |
|---|---|
| `validation_flag` | 0 = no automated validation violation; 1 = invalid parameter; 2 = suspect |
| `row_qc` | Final record class: VALID, SUSPECT, ENVIRONMENTAL_EVENT, or INVALID_PARAMETER |
| `environmental_event` | Contextual indicator that a record represents a genuine environmental event |
| `imperfection_type` | Sensor/telemetry imperfection tag, where identified |
| `flag_reason` | Rule/stage explanation where an automated rule generated a flag |
| `maintenance` | Maintenance-window indicator |
| `anomaly_event` | Anomaly-event indicator used in the dataset |
| `alert` | Alert/status information, where present |
| `rainfall_mm_hr` | Rainfall value associated with the record. Every wet day carries an identical 10-hour profile (12:00 to 21:00 UTC), so this column holds daily totals distributed over fixed hours and carries no sub-daily timing |

## Cleaned measurements
`pH_clean`, `temperature_clean`, `turbidity_clean`, `ec_clean`, `tds_clean`, and `do_clean` are the QC-retained measurement fields used for statistical analysis.
