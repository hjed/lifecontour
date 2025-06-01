#!/bin/sh
set -e

# Health check for frontend service
curl -f http://localhost:3000 || exit 1
