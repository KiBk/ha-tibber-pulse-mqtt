# Original measurement timestamps

Some Pulse HAN firmware bundles multiple meter telegrams in one MQTT message.
For example, a Norwegian Kaifa meter can send power every two seconds while
the Pulse delivers five telegrams together every ten seconds. The decoder
preserves each valid telegram date/time on instantaneous measurement entities:

```yaml
measurement_timestamp: "2025-07-08T10:30:02+00:00"
measurement_timestamp_source: home_assistant_time_zone
```

`measurement_timestamp` is UTC and belongs to that sensor value. Consecutive
equal power values still have distinct timestamps and therefore distinct
recordable state attributes. Value, timestamp and current device status are
updated together. Status-only updates retain the previous measurement time.
An untimestamped or invalidly timestamped new reading clears it instead of
attaching the previous measurement's time to a new value.

## Clock interpretation

- A valid DLMS deviation supplies the UTC offset (`dlms_deviation`).
- If the deviation is unspecified (`0x8000`), the integration uses **Home
  Assistant's configured timezone**, which must match the meter's local clock.
  Norwegian KFM meters use Norwegian local time; configure `Europe/Oslo`.
- Spring DST gaps are rejected; ambiguous autumn times are resolved only when
  exactly one UTC candidate is close to the current receipt/processing time.
- Invalid/doubtful clock flags, incomplete dates, times over five minutes old,
  or times over five seconds ahead are not accepted. Power still updates.
- No timestamp is invented for other message formats without a valid time.
- The telegram time is not applied to cumulative energy registers: an hourly
  energy snapshot can refer to a different boundary from the telegram itself.

## History and NILM

**HA's native `last_updated` and `last_changed` remain receipt/state timestamps.**
This integration does not backdate state-machine events, rewrite the recorder
database, or replay old readings with artificial delays. Standard HA graphs and
statistics still use HA's own timestamps. Existing history cannot recover
discarded original timestamps retroactively.

Recorder stores the added attributes under the existing retention policy.
Clients must request **full history with attributes** and use
`attributes.measurement_timestamp`. Do not use `minimal_response` or
`no_attributes`; these can omit per-reading metadata.

For example, request one sensor's history through the normal authenticated HA
REST API, with a bounded start/end range:

```text
GET /api/history/period/<start>?filter_entity_id=<power-entity>&end_time=<end>
```

Save that JSON locally, then export it using the included standard-library tool:

```sh
python tools/export_measurement_history.py history.json > measurements.csv
```

The CSV contains UTC measurement time and watts. The exporter sorts by original
time, collapses status-only duplicates, rejects conflicting values at one time,
and skips untimestamped readings rather than substituting arrival time.

HA-NILM currently reads `last_updated`/`last_changed` and requests minimal
history. It needs a separate reader adaptation to use this metadata for both
historical training and live inference; installing this change alone does not
make stock HA-NILM use original times. Older readings must remain explicitly
identified as arrival-timed data when assembling mixed training datasets.
