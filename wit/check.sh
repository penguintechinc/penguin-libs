#!/usr/bin/env bash
# Verifies the penguin:tools WIT package parses and matches the committed golden snapshot.
set -euo pipefail
cd "$(dirname "$0")"
diff -u penguin-tools.golden.wit <(wasm-tools component wit penguin-tools)
echo "penguin:tools WIT matches golden"
