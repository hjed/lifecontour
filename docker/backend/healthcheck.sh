#!/bin/bash
set -e

# Health check for backend service
curl -f http://localhost:8000/api/health || exit 1
