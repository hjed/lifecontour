#!/bin/sh
set -e

# Frontend is serving (addressed by service name, not localhost)
curl -f http://frontend:3000

# Backend is reachable directly — NOT via the Next.js proxy rewrite
curl -f "${BACKEND_URL:-http://backend:8000}/api/health"
