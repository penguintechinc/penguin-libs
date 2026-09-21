#!/usr/bin/env bash
set -euo pipefail

OUT="${1:?usage: gen-test-tls.sh <output-dir> <server-hostname>}"
SERVER_HOSTNAME="${2:?usage: gen-test-tls.sh <output-dir> <server-hostname>}"

mkdir -p "$OUT"

openssl req -x509 -newkey rsa:2048 -days 1 -nodes -sha256 \
  -keyout "$OUT/ca.key" -out "$OUT/ca.crt" \
  -subj "/CN=penguin-spine-test-ca"

openssl req -newkey rsa:2048 -nodes -sha256 \
  -keyout "$OUT/server.key" -out "$OUT/server.csr" \
  -subj "/CN=$SERVER_HOSTNAME"

openssl x509 -req -in "$OUT/server.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" \
  -CAcreateserial -days 1 -sha256 -out "$OUT/server.crt" \
  -extfile <(printf "subjectAltName=DNS:%s,DNS:localhost,IP:127.0.0.1" "$SERVER_HOSTNAME")

rm -f "$OUT/server.csr" "$OUT/ca.srl"
chmod 644 "$OUT"/*.crt "$OUT"/*.key

echo "wrote ca.crt, server.crt, server.key (CN=$SERVER_HOSTNAME) to $OUT"
