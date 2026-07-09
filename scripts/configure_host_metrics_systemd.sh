#!/usr/bin/env bash
set -euo pipefail

bind_ip="${MINYAD_METRICS_BIND_IP:-192.168.110.2}"

if [[ "${bind_ip}" == "127.0.0.1" || "${bind_ip}" == "::1" ]]; then
  echo "Refusing to configure host metrics on loopback: ${bind_ip}" >&2
  exit 1
fi

if [[ "$#" -eq 0 ]]; then
  echo "Usage: $0 unit.service [unit.service ...]" >&2
  exit 1
fi

for unit in "$@"; do
  if [[ "${unit}" != *.service ]]; then
    continue
  fi

  dropin_dir="/etc/systemd/system/${unit}.d"
  dropin="${dropin_dir}/10-minyad-metrics-bind.conf"
  tmp="$(mktemp)"

  cat >"${tmp}" <<EOF
[Service]
Environment=METRICS_ADDR=${bind_ip}
EOF

  install -d -m 0755 "${dropin_dir}"
  install -m 0644 "${tmp}" "${dropin}"
  rm -f "${tmp}"
  echo "Configured ${unit} metrics bind address: ${bind_ip}"
done

systemctl daemon-reload
