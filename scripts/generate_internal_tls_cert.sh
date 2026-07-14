#!/bin/sh
# Generates the self-signed internal TLS cert/key used between Minyad's own
# containers, if one doesn't already exist. Reads MINYAD_TLS_IP_SANS (comma
# separated) and MINYAD_HOST_DNS from the environment. Run by the
# minyad-tls-init service in docker-compose.yml.
set -e

mkdir -p /run/minyad/tls
if [ ! -s /run/minyad/tls/internal.crt ] || [ ! -s /run/minyad/tls/internal.key ]; then
  tls_ip_sans="${MINYAD_TLS_IP_SANS:-}"
  ip_san_lines=""
  ip_san_index=1
  for ip_san in $(printf '%s' "$tls_ip_sans" | tr ',' ' '); do
    ip_san_lines="${ip_san_lines}IP.${ip_san_index} = ${ip_san}
"
    ip_san_index=$((ip_san_index + 1))
  done
  cat > /tmp/minyad-internal-openssl.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = minyad-internal

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = minyad-api
DNS.2 = minyad-strategy
DNS.3 = minyad
DNS.4 = dryad
DNS.5 = localhost
DNS.6 = ${MINYAD_HOST_DNS:-minyad-host.example}
${ip_san_lines}
EOF
  openssl req -x509 -newkey rsa:4096 -sha256 -days 36500 -nodes \
    -keyout /run/minyad/tls/internal.key \
    -out /run/minyad/tls/internal.crt \
    -config /tmp/minyad-internal-openssl.cnf
fi
chown 1000:1000 /run/minyad/tls/internal.crt /run/minyad/tls/internal.key
chmod 0644 /run/minyad/tls/internal.crt
chmod 0640 /run/minyad/tls/internal.key
