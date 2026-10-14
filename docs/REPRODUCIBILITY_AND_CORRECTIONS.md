# Reproducibility and correction notes

This public package was critically reviewed against the released CSV, the supplied analysis script, the dissertation methods/results, and the available ESP32 firmware.

## Corrections made
1. Removed hard-coded absolute input paths from the analysis workflow; repository-relative paths are now used by default and command-line overrides are supported.
2. Standardised all timestamps to UTC and sort order before temporal analysis.
3. Removed the `value_value_counts()` workaround and use the correct pandas API.
4. Removed duplicated WQI and plotting sections.
5. Corrected the sensor/reference section: raw telemetry versus QC-cleaned telemetry is not called laboratory validation. A separate laboratory reference file is included from the dissertation appendix for the six paired events.
6. Added explicit laboratory MAE, RMSE, bias and R² calculations for the six paired reference events.
7. Corrected Isolation Forest preprocessing to use the documented zero-mean/unit-variance feature standardisation and to train on records with `validation_flag == 0` in the first two weeks. The model remains at 100 estimators, contamination 0.05 and random state 42.
8. Made the centred Stage-4 window explicit as 25 hourly observations, which spans 24 hours from the first to last observation while being centred on the target observation.
9. Corrected the Water Quality Index implementation to the final dissertation method: Brown weighted arithmetic method, five parameters (pH, DO, turbidity, TDS and EC), inverse permissible-standard weights, DO inverted quality rating using 14.6 mg/L as the ideal value, temperature excluded, and the dissertation classification scale (Excellent ≤25, Good 26–50, Poor 51–75, Very Poor 76–100, Unfit >100).
10. Removed the previously supplied C++ implementation from the public reproduction package because it was not the original analysis implementation and could not guarantee library-equivalent Isolation Forest, statistical or WQI results.
11. Added a reconstructed Node-RED reference flow using the actual feed names exposed by the available firmware. It is clearly labelled as reconstructed rather than the original deployed export.
12. Added a data dictionary, setup instructions, provenance notes and integrity manifest.

## Important methodological distinction
The historical cleaned CSV contains contextual labels (`environmental_event`, `imperfection_type`) that cannot be recreated from the six Adafruit IO parameter feeds alone. The reconstructed Node-RED flow therefore supports those fields but does not fabricate them. An external rainfall/event source and maintenance/event log are required for equivalent contextual adjudication.

## WQI note
The supplied analysis document contained a different WQI implementation (including temperature and a simplified DO formula). The final dissertation explicitly describes the five-parameter Brown implementation with temperature excluded and DO inverted. The public repository follows the final dissertation method. Any manuscript tables based on the older implementation should be regenerated from `analysis_reproduction.py` before submission.

## Firmware correction and provenance

The supplied `Smart_Water_Monitor` sketch was retained unchanged as provenance but was not presented as the historical deployment firmware. A separate reference implementation was added under `firmware/reference_deployment/` to match the documented architecture: Atlas Scientific EZO-pH/EZO-DO/EZO-EC, DS18B20 temperature, TS-300B turbidity, hourly acquisition, JSON packets, MQTT transport, and a 128-slot SPIFFS transmission buffer. The turbidity calibration coefficients are deliberately left as explicit deployment configuration because the supplied files did not provide the historical TS-300B voltage-to-NTU calibration curve.


## Corrections added after comparison with the manuscripts (Paper 1 Rev. 9)
13. **Isolation Forest training definition.** The earlier script trained only on `validation_flag == 0` records, which does not reproduce the results reported in the dissertation and manuscript. The primary run now fits on all complete cleaned records (initial 14-day window, then all complete records before each month), which reproduces the reported counts exactly (monthly retraining composite: TP 59, FP 268, FN 95, TN 701; static composite: TP 142, FP 872, FN 12, TN 97). The Flag-0-only variant is kept as `results/isolation_forest_performance_flag0_training_sensitivity.csv`.
14. **Stage 4 window.** The validation log shows that the deployed check compared each record with the mean of the 24 preceding readings (current record excluded): the logged means match this window in 99% of 178 cases and match no centred window. The reconstructed flow now implements the trailing window. The earlier centred 25-observation design is withdrawn.
15. **Rate-of-change limits.** The deployed log records 1.5 (pH), 3 mg/L (DO) and 500 NTU (turbidity) per hour. Temperature, EC and TDS limits never triggered and are not recoverable. The limits for those three in the reconstructed flow are placeholders chosen above the largest accepted hourly changes (2.29 °C, 95.3 µS/cm, 48.2 mg/L) and must be replaced by the implemented values if they are known.
16. **Rainfall resolution.** In `rainfall_mm_hr` every wet day carries an identical hourly profile (ten hours, 12:00 to 21:00 UTC), so the column holds daily totals and no sub-daily timing. Do not use it for hourly lag analysis.
