# Minyad Monitoring

Prometheus instrumentation is implemented service-by-service. The monitoring host, VPN, HAProxy, and firewall boundary live outside this repository; this repo only defines the service metrics endpoints, Prometheus snippets, and metric contracts.

## Port Plan

| Port | Service | Status | Notes |
|---:|---|---|---|
| 9101 | minyad-api | implemented | FastAPI `/metrics`; host port maps to the API container port. |
| 9102 | minyad-ingestion | implemented | `prometheus_client.start_http_server`; published with `MINYAD_METRICS_BIND_IP`. |
| 9103 | minyad-control | implemented | Plain Python metrics endpoint; published with `MINYAD_METRICS_BIND_IP`. |
| 9104 | minyad-strategy-v3 | implemented | Strategy v3 metrics endpoint; published with `MINYAD_METRICS_BIND_IP`. |
| 9105 | minyad-trade | implemented | Plain Python metrics endpoint; published with `MINYAD_METRICS_BIND_IP`. |
| 9106 | minyad-mqtt-observer | implemented | Sidecar observer for the Mosquitto container; published with `MINYAD_METRICS_BIND_IP`. |
| 9107 | goodwe_bridge | implemented | Host systemd service metrics endpoint; bind with `METRICS_ADDR`. |
| 9108 | dsmr_bridge | implemented | Host systemd service metrics endpoint; bind with `METRICS_ADDR`. |
| 9109 | enphase_bridge | implemented | Host systemd service metrics endpoint; bind with `METRICS_ADDR`. |
| 9110 | node_exporter | implemented | `prom/node-exporter`, published with `MINYAD_METRICS_BIND_IP`. |
| 9111 | cAdvisor | implemented | `gcr.io/cadvisor/cadvisor`, published with `MINYAD_METRICS_BIND_IP`. |

## Battery Power Sign Convention

Battery power follows the existing Minyad convention: positive `battery_power_w` means battery discharge, negative means battery charge.

## Metric Catalog

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `minyad_ingestion_build_info` | Gauge | `version` | Build/version marker; always `1` for the running ingestion build. |
| `minyad_ingestion_errors_total` | Counter | `type` | Ingestion errors by low-cardinality error type. |
| `minyad_ingestion_samples_total` | Counter | `source` | Processed sensor samples. Currently `source="dsmr"`. |
| `minyad_ingestion_last_sample_timestamp_seconds` | Gauge | `source` | Unix timestamp for the most recent processed sensor sample; primary staleness signal. |
| `minyad_ingestion_write_duration_seconds` | Histogram | none | Duration of database writes for ingested grid points and rollups. |
| `minyad_control_build_info` | Gauge | `version` | Build/version marker; always `1` for the running control build. |
| `minyad_control_errors_total` | Counter | `type` | Control errors by low-cardinality error type. |
| `minyad_control_battery_soc_ratio` | Gauge | none | Latest battery state of charge, 0-1. |
| `minyad_control_battery_power_watts` | Gauge | none | Latest battery power; positive discharge, negative charge. |
| `minyad_control_grid_power_watts` | Gauge | none | Latest grid power; positive import, negative export. |
| `minyad_control_pv_power_watts` | Gauge | none | Latest PV production received from MQTT. |
| `minyad_bridge_goodwe_build_info` | Gauge | `version` | Build/version marker; always `1` for the running GoodWe bridge. |
| `minyad_bridge_goodwe_errors_total` | Counter | `type` | GoodWe bridge errors by low-cardinality error type. |
| `minyad_bridge_goodwe_read_duration_seconds` | Histogram | none | Duration of GoodWe read calls. |
| `minyad_bridge_goodwe_read_failures_total` | Counter | none | GoodWe read failures. |
| `minyad_bridge_goodwe_last_success_timestamp_seconds` | Gauge | none | Unix timestamp for the most recent successful GoodWe read. |
| `minyad_strategy_build_info` | Gauge | `version` | Build/version marker; always `1` for the running strategy v3 build. |
| `minyad_strategy_errors_total` | Counter | `type` | Strategy v3 errors by low-cardinality error type. |
| `minyad_strategy_solve_duration_seconds` | Histogram | none | Duration of strategy v3 plan recalculations. |
| `minyad_strategy_solve_status_total` | Counter | `status` | Strategy v3 solve outcomes: `optimal`, `infeasible`, `timeout`, or `error`. |
| `minyad_strategy_plan_horizon_hours` | Gauge | none | Current plan horizon in hours. |
| `minyad_strategy_last_plan_timestamp_seconds` | Gauge | none | Unix timestamp for the most recent generated plan. |
| `minyad_strategy_planned_battery_power_watts` | Gauge | none | Planned battery power for the next interval; positive discharge, negative charge. |
| `minyad_trade_build_info` | Gauge | `version` | Build/version marker; always `1` for the running trade build. |
| `minyad_trade_errors_total` | Counter | `type` | Trade errors by low-cardinality error type. |
| `minyad_trade_last_fetch_success_timestamp_seconds` | Gauge | none | Unix timestamp for the most recent successful price fetch. |
| `minyad_trade_fetch_failures_total` | Counter | none | Day-ahead price fetch failures. |
| `minyad_trade_prices_available_hours` | Gauge | none | Hours of future prices available from the latest successful fetch. |
| `minyad_bridge_dsmr_build_info` | Gauge | `version` | Build/version marker; always `1` for the running DSMR bridge. |
| `minyad_bridge_dsmr_errors_total` | Counter | `type` | DSMR bridge errors by low-cardinality error type. |
| `minyad_bridge_dsmr_last_success_timestamp_seconds` | Gauge | none | Unix timestamp for the most recent successful DSMR bridge publish. |
| `minyad_bridge_enphase_build_info` | Gauge | `version` | Build/version marker; always `1` for the running Enphase bridge. |
| `minyad_bridge_enphase_errors_total` | Counter | `type` | Enphase bridge errors by low-cardinality error type. |
| `minyad_bridge_enphase_last_success_timestamp_seconds` | Gauge | none | Unix timestamp for the most recent successful Enphase bridge poll. |
| `minyad_api_build_info` | Gauge | `version` | Build/version marker; always `1` for the running API build. |
| `minyad_api_errors_total` | Counter | `type` | API errors by low-cardinality error type. Reserved for explicit API error instrumentation. |
| FastAPI instrumentator HTTP metrics | Counter/Histogram/Gauge | method, handler, status | Standard HTTP request metrics exported by `prometheus-fastapi-instrumentator`. |
| `minyad_mqtt_build_info` | Gauge | `version` | Build/version marker; always `1` for the MQTT observer build. |
| `minyad_mqtt_errors_total` | Counter | `type` | MQTT observer errors by low-cardinality error type. |
| `minyad_mqtt_messages_total` | Counter | `topic_group` | Observed MQTT messages grouped into a fixed topic set. |
| `minyad_mqtt_connected` | Gauge | none | MQTT observer connection state, `1` connected and `0` disconnected. |

## Alert Constants

Strategy v3 defaults to `strategy3.plan_interval_min = 15`, so the strategy staleness alert uses a 30 minute threshold.

## Scrape Config

See `prometheus/minyad-scrape.yml`.

## Alert Rules

See `prometheus/minyad-alerts.yml`.

## Recording Rules

See `prometheus/minyad-recording.yml`.

## Findings

- `vesper` and `kairos` are listed in the monitoring brief but are not present in this repository or Docker Compose file.
- `dryad` is implemented as API functionality in `api/dryad.py`, not as a separate service.
- `minyad-mqtt` is an Eclipse Mosquitto container, so MQTT metrics are implemented through the `minyad-mqtt-observer` sidecar rather than by modifying Mosquitto itself.
- This repository's `minyad-ingestion` service currently ingests DSMR only. GoodWe and Enphase freshness are therefore represented by bridge metrics rather than `minyad_ingestion_last_sample_timestamp_seconds{source="goodwe|enphase"}`.
