# Provenance

The cleaned and raw CSV files are the supplied study files. Laboratory reference values were transcribed from Appendix Table A.1 of the dissertation. The Python analysis workflow is a corrected public reproduction script. The Node-RED flow is a reconstruction from the documented architecture and available implementation materials; the original exported flow was not supplied and is therefore not represented as the original historical flow.

## Firmware

The repository provides one definitive firmware implementation aligned with the monitoring architecture documented for the study. It implements the documented sensor set, hourly acquisition, JSON measurement records, MQTT communication, and a 128-record SPIFFS circular transmission buffer. Sensor calibration constants that are not recoverable from the released materials, particularly the TS-300B voltage-to-NTU relationship, are explicitly configurable and must be validated before field deployment.
