#!/bin/sh

# Hydra Entrypoint Script
# This script starts Hydra and then initializes the OAuth client in the background

set -e

echo "🚀 Starting Hydra OAuth Provider..."

# Start the initialization script in the background
# This will wait for Hydra to be ready and then create the OAuth client
if [ -f "/init-oauth.sh" ]; then
    echo "📋 Starting OAuth client initialization in background..."
    chmod +x /init-oauth.sh
    /init-oauth.sh &
    INIT_PID=$!
    echo "🔧 OAuth initialization started (PID: $INIT_PID)"
else
    echo "⚠️  OAuth initialization script not found"
fi

# Start Hydra with the provided arguments
echo "🔐 Starting Hydra server..."
exec "$@"
