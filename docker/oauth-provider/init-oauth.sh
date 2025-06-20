#!/bin/sh

# OAuth Provider Initialization Script
# This script creates the OAuth client automatically when the container starts

echo "Starting OAuth provider initialization..."

# Wait for Hydra to be ready
echo "Waiting for Hydra to start..."
sleep 10

# Check if Hydra is ready
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -f http://localhost:4445/health/ready >/dev/null 2>&1; then
        echo "Hydra is ready!"
        break
    fi
    echo "Waiting for Hydra to be ready... (attempt $((attempt + 1))/$max_attempts)"
    sleep 2
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    echo "ERROR: Hydra failed to start within expected time"
    exit 1
fi

# Create OAuth client
echo "Creating OAuth client..."
curl -X POST http://localhost:4445/admin/clients \
    -H "Content-Type: application/json" \
    -d '{
        "client_id": "dev-client-id",
        "client_secret": "dev-client-secret",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "redirect_uris": ["http://localhost:8000/auth/callback"],
        "scope": "openid profile email",
        "skip_consent": true,
        "skip_logout_consent": true,
        "client_name": "Personal Management System (Development)",
        "client_uri": "http://localhost:3000"
    }'

if [ $? -eq 0 ]; then
    echo "OAuth client created successfully!"
else
    echo "WARNING: Failed to create OAuth client (may already exist)"
fi

echo "OAuth provider initialization complete."
