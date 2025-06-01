#!/bin/sh
set -e

# Health check for nginx service
curl -f http://localhost:80/health || exit 1
