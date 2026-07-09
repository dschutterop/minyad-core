# Prometheus Handoff

This is the monitoring-host runbook for scraping Minyad. The Minyad host exposes metrics on the ports listed in `docs/monitoring.md`, bound to the VPN/internal interface by default.

## Files To Copy

Copy these files from this repository to the Prometheus host:

| Source | Suggested destination |
|---|---|
| `prometheus/minyad-scrape.yml` | `/etc/prometheus/file_sd/minyad-scrape.yml` or another included scrape snippet path |
| `prometheus/minyad-alerts.yml` | `/etc/prometheus/rules/minyad-alerts.yml` |
| `prometheus/minyad-recording.yml` | `/etc/prometheus/rules/minyad-recording.yml` |

## Required Edit

Replace every `minyad-host.example` target in `minyad-scrape.yml` with the DNS name or VPN/internal IP of the Minyad host as seen from Prometheus.

Example:

```yaml
targets:
  - 192.168.110.2:9102
```

Keep the `stack: minyad` label. Alerts rely on it, especially `up{stack="minyad"} == 0`.

## Prometheus Include Example

If the Prometheus host uses direct config snippets, add this to `prometheus.yml`:

```yaml
scrape_config_files:
  - /etc/prometheus/file_sd/minyad-scrape.yml

rule_files:
  - /etc/prometheus/rules/minyad-alerts.yml
  - /etc/prometheus/rules/minyad-recording.yml
```

If your Prometheus version or packaging does not support `scrape_config_files`, paste the `scrape_configs` entries from `minyad-scrape.yml` into the main `scrape_configs:` list.

## Targets

| Job | Target port | Notes |
|---|---:|---|
| `minyad-api` | 9101 | FastAPI `/metrics`. |
| `minyad-ingestion` | 9102 | DSMR ingestion metrics. |
| `minyad-control` | 9103 | Battery/grid/PV control gauges. |
| `minyad-strategy-v3` | 9104 | Solver and plan freshness metrics. |
| `minyad-trade` | 9105 | ENTSO-E fetch freshness and price horizon. |
| `minyad-mqtt` | 9106 | MQTT observer sidecar. |
| `minyad-bridge-goodwe` | 9107 | Host GoodWe bridge. |
| `minyad-bridge-dsmr` | 9108 | Host DSMR bridge. |
| `minyad-bridge-enphase` | 9109 | Host Enphase bridge. |
| `minyad-node-exporter` | 9110 | Host metrics. |
| `minyad-cadvisor` | 9111 | Container metrics. |

## Validation On The Prometheus Host

Run:

```bash
promtool check config /etc/prometheus/prometheus.yml
promtool check rules /etc/prometheus/rules/minyad-alerts.yml /etc/prometheus/rules/minyad-recording.yml
```

Optional quick scrapes:

```bash
curl -fsS http://192.168.110.2:9102/metrics | grep minyad_ingestion_build_info
curl -fsS http://192.168.110.2:9103/metrics | grep minyad_control_build_info
curl -fsS http://192.168.110.2:9104/metrics | grep minyad_strategy_build_info
curl -fsS http://192.168.110.2:9105/metrics | grep minyad_trade_build_info
curl -fsS http://192.168.110.2:9106/metrics | grep minyad_mqtt_build_info
curl -fsS http://192.168.110.2:9107/metrics | grep minyad_bridge_goodwe_build_info
curl -fsS http://192.168.110.2:9108/metrics | grep minyad_bridge_dsmr_build_info
curl -fsS http://192.168.110.2:9109/metrics | grep minyad_bridge_enphase_build_info
```

Then reload Prometheus:

```bash
curl -X POST http://127.0.0.1:9090/-/reload
```

Use your service manager instead if lifecycle reloads are disabled:

```bash
systemctl reload prometheus
```

## First PromQL Checks

Use these in the Prometheus UI after reload:

```promql
up{stack="minyad"}
minyad:ingestion_sample_age_seconds
minyad:strategy_plan_age_seconds
minyad_trade_prices_available_hours
minyad_control_battery_soc_ratio
rate(minyad_mqtt_messages_total[5m])
```

## Alertmanager Labels

The rule files set:

```yaml
labels:
  severity: warning|critical
  stack: minyad
```

Route on `stack="minyad"` or the existing `severity` labels in Alertmanager. No custom receiver name is required by these rule files.

## Notes

- Strategy v3 defaults to a 15 minute plan interval; the stale-plan alert fires after 30 minutes.
- `minyad-ingestion` currently exposes DSMR sample freshness. GoodWe and Enphase freshness come from bridge metrics.
- MQTT metrics use fixed `topic_group` labels only; raw topics are intentionally not labels.
