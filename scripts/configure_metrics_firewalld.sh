#!/usr/bin/env bash
set -euo pipefail

zone="${MINYAD_FIREWALL_ZONE:-public}"
ports="${MINYAD_METRICS_PORT_RANGE:-9101-9111}"
source="${MINYAD_PROMETHEUS_SOURCE:-}"

if ! command -v firewall-cmd >/dev/null 2>&1; then
  echo "firewall-cmd is required to configure Minyad metrics access" >&2
  exit 1
fi

if [[ "$(firewall-cmd --state 2>/dev/null)" != "running" ]]; then
  echo "firewalld is not running; leaving metrics firewall rules unchanged" >&2
  exit 1
fi

if [[ -n "${source}" ]]; then
  family="ipv4"
  if [[ "${source}" == *:* ]]; then
    family="ipv6"
  fi
  rule="rule family=\"${family}\" source address=\"${source}\" port port=\"${ports}\" protocol=\"tcp\" accept"
  if ! firewall-cmd --permanent --zone="${zone}" --query-rich-rule="${rule}" >/dev/null; then
    firewall-cmd --permanent --zone="${zone}" --add-rich-rule="${rule}"
  fi
else
  if ! firewall-cmd --permanent --zone="${zone}" --query-port="${ports}/tcp" >/dev/null; then
    firewall-cmd --permanent --zone="${zone}" --add-port="${ports}/tcp"
  fi
fi

firewall-cmd --reload
firewall-cmd --zone="${zone}" --list-all
