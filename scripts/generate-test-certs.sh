#!/usr/bin/env bash
# generate-test-certs.sh — Generate self-signed TLS certs for local HTTP/3 testing.
# Usage: ./scripts/generate-test-certs.sh [output-dir]
# Default output: ./certs/

set -euo pipefail

CERT_DIR="${1:-./certs}"
mkdir -p "$CERT_DIR"

DAYS=365
SUBJ="/C=US/O=PenguinTech/CN=localhost"

echo "Generating self-signed TLS certificate for localhost..."

# Generate CA key and cert
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -days "$DAYS" -nodes \
    -keyout "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -subj "$SUBJ" \
    2>/dev/null

# Generate server key and CSR
openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -nodes \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" \
    -subj "$SUBJ" \
    2>/dev/null

# Create SAN extension config
cat > "$CERT_DIR/san.cnf" << 'SANEOF'
[v3_req]
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
DNS.2 = *.localhost
IP.1 = 127.0.0.1
IP.2 = ::1
SANEOF

# Sign server cert with CA
openssl x509 -req \
    -in "$CERT_DIR/server.csr" \
    -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERT_DIR/server.crt" \
    -days "$DAYS" \
    -extensions v3_req \
    -extfile "$CERT_DIR/san.cnf" \
    2>/dev/null

# Clean up intermediate files
rm -f "$CERT_DIR/server.csr" "$CERT_DIR/san.cnf" "$CERT_DIR/ca.srl"

echo "Certificates generated in $CERT_DIR/"
echo "  CA:          $CERT_DIR/ca.crt"
echo "  Server cert: $CERT_DIR/server.crt"
echo "  Server key:  $CERT_DIR/server.key"
