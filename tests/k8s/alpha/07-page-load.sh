#!/bin/bash

# === Page Load Tests Step ===
# For library repos: this is a no-op
# Library packages don't serve web pages - they are NPM packages

set -e

echo "Library repo - no web UI to test"
echo "Page load tests skipped for library package"
exit 0
