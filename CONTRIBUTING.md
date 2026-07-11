# Contributing to Minyad Core

Thanks for helping make the reusable Minyad plumbing better for home-energy operators.

## Hardware Reports

When reporting compatibility issues, please include the device model, firmware version, bridge path, connection type, and the exact symptom. For example: inverter model, battery model, RS485 adapter or Ethernet bridge, Modbus device ID, DSMR/P1 source, Envoy model, and the relevant log excerpt with secrets removed.

## Pull Requests

Keep changes focused and vendor-agnostic where possible. Bridges should publish stable MQTT topics, fail visibly, and avoid assumptions that only hold for one private installation.

Never commit secrets, real tokens, private hostnames, public IP addresses, private IP addresses, MAC addresses, `.env` files, certificate material, or screenshots that reveal local infrastructure.

Strategy, trading, scheduling, and operator-agent features are out of scope for this public core repository.

