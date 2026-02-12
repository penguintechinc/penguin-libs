#!/bin/bash

# === Build Images Step ===
# For library repos: this is a no-op, as we don't build custom images
# The Helm chart uses official Node image from registry

set -e

echo "Library repo - no custom Docker images to build"
echo "Using official Node:20-alpine image from registry"
exit 0
