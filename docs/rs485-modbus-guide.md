# RS485 and Modbus Guide

This guide captures the reusable lessons from moving a GoodWe/Dyness installation from fragile WiFi polling toward a wired RS485 to Ethernet Modbus path.

## Why RS485 to Ethernet

WiFi dongles are convenient for setup, but they are a poor foundation for closed-loop battery control. In practice, the reliable path is a wired RS485 connection from the inverter to an Ethernet Modbus gateway, with MQTT used as the stable integration boundary for the rest of the stack.

## Tested Shape

- Inverter: GoodWe ES-family hybrid inverter.
- Battery: Dyness DL-series battery packs behind the inverter.
- Metering: DSMR/P1 grid meter and Enphase Envoy-S Metered production telemetry.
- Bridge: RS485 A/B pair into an Ethernet Modbus TCP gateway such as a Waveshare RS485-to-Ethernet device.
- Protocol boundary: host-side bridge reads or writes device state, then publishes sanitized state to MQTT.

## Wiring Checklist

- Use twisted pair for RS485 A/B and keep the run away from noisy AC cabling where possible.
- Confirm A/B polarity at both ends. If every request times out, swap A and B before changing software.
- Use one termination strategy for the bus. Avoid stacking terminators blindly.
- Keep the Modbus device ID explicit; many GoodWe examples use `247`, but your installation may differ.
- Put the Ethernet gateway on a stable LAN address or DHCP reservation.
- Keep the gateway reachable only from the trusted automation network.

## Gateway Settings

Typical starting point:

```text
Mode: Modbus TCP to RTU
TCP port: 502
Serial baud rate: match inverter setting
Data bits: 8
Parity: none, unless your inverter is configured otherwise
Stop bits: 1
Device ID: match inverter Modbus slave ID
```

Treat these as starting values, not universal truth. The device manual and the inverter configuration screen are the authority for your hardware.

## Register Map Notes

The public bridge intentionally keeps Modbus usage narrow:

- Telemetry is published as MQTT state.
- Charge and discharge limit writes are actuator ceilings, not force-charge or force-discharge commands.
- Unsupported EMS force-control registers should fail closed and be left out of default examples.

For GoodWe ES-style installations, validate any register against your inverter firmware before automating writes. Keep dry-run enabled until reads are stable and the target register behavior is understood.

## MQTT Topics

The bridge publishes public integration topics such as:

```text
minyad/battery/power_w
minyad/battery/mode
minyad/grid/net_power_w
minyad/control/charge_w
minyad/control/discharge_w
minyad/bridge/status
```

Downstream services should depend on these MQTT topics rather than importing host bridge internals.

## Operational Lessons

- Prefer a small, observable bridge over a large all-in-one controller.
- Publish `last_seen` and bridge status topics so stale hardware data is visible.
- Expose Prometheus metrics on a trusted interface only.
- Make Modbus writes rate-limited and idempotent.
- Keep a dry-run mode for commissioning and firmware changes.
- Document local register findings, but do not publish private addresses, serial numbers, tokens, or LAN topology.

## Troubleshooting

- No responses: check A/B polarity, gateway mode, device ID, baud rate, and firewall rules.
- Intermittent reads: shorten cable runs, inspect termination, and check for shared power noise.
- Writes appear accepted but behavior does not change: confirm whether the register is a limit, a setting, or a true control command.
- MQTT is quiet: verify broker host, credentials, topic prefix, and bridge logs before changing Modbus settings.

