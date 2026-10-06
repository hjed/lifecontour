# Fix OAuth Client Configuration Script (PowerShell)
# This script fixes the OAuth client configuration in Hydra to ensure correct redirect URIs

Write-Host "🔧 Fixing OAuth Client Configuration" -ForegroundColor Blue
Write-Host "====================================" -ForegroundColor Blue

function Write-Step {
    param([string]$Message)
    Write-Host "`n📋 $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "✅ $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "⚠️  $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "❌ $Message" -ForegroundColor Red
}

# Check if Hydra is running
Write-Step "Checking Hydra availability..."
try {
    $response = Invoke-WebRequest -Uri "http://localhost:4445/health/ready" -Method GET -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Success "Hydra is accessible"
    } else {
        throw "Unexpected status code: $($response.StatusCode)"
    }
} catch {
    Write-Error "Hydra admin endpoint is not accessible at http://localhost:4445"
    Write-Error "Make sure Docker Compose is running: docker compose -f docker-compose.dev.yml up -d"
    exit 1
}

# Delete existing client if it exists
Write-Step "Removing existing OAuth client..."
try {
    Invoke-WebRequest -Uri "http://localhost:4445/admin/clients/dev-client-id" -Method DELETE -UseBasicParsing | Out-Null
    Write-Success "Existing OAuth client removed"
} catch {
    Write-Warning "OAuth client may not exist (this is okay)"
}

# Wait a moment for deletion to complete
Start-Sleep -Seconds 2

# Create new OAuth client with correct configuration
Write-Step "Creating new OAuth client with correct configuration..."

$clientConfig = @{
    client_id = "dev-client-id"
    client_secret = "dev-client-secret"
    grant_types = @("authorization_code", "refresh_token")
    response_types = @("code")
    redirect_uris = @("http://localhost:3000/auth/callback")
    scope = "openid profile email"
    skip_consent = $true
    skip_logout_consent = $true
    client_name = "Lifecontour (Development)"
    client_uri = "http://localhost:3000"
    token_endpoint_auth_method = "client_secret_post"
} | ConvertTo-Json -Depth 10

try {
    $headers = @{
        "Content-Type" = "application/json"
    }

    Invoke-WebRequest -Uri "http://localhost:4445/admin/clients" -Method POST -Body $clientConfig -Headers $headers -UseBasicParsing | Out-Null
    Write-Success "OAuth client created successfully"
} catch {
    Write-Error "Failed to create OAuth client: $($_.Exception.Message)"
    exit 1
}

# Verify client configuration
Write-Step "Verifying OAuth client configuration..."
try {
    $clientResponse = Invoke-WebRequest -Uri "http://localhost:4445/admin/clients/dev-client-id" -Method GET -UseBasicParsing
    $clientInfo = $clientResponse.Content | ConvertFrom-Json

    if ($clientInfo.client_id -eq "dev-client-id") {
        Write-Success "Client ID verified"
    } else {
        Write-Error "Client ID verification failed"
        exit 1
    }

    if ($clientInfo.redirect_uris -contains "http://localhost:3000/auth/callback") {
        Write-Success "Redirect URI verified"
    } else {
        Write-Error "Redirect URI verification failed"
        Write-Host "Current redirect URIs: $($clientInfo.redirect_uris -join ', ')"
        exit 1
    }

    if ($clientInfo.grant_types -contains "authorization_code") {
        Write-Success "Grant types verified"
    } else {
        Write-Error "Grant types verification failed"
        exit 1
    }

    # Display client configuration
    Write-Step "OAuth Client Configuration Summary"
    Write-Host "=================================="
    Write-Host "Client ID: $($clientInfo.client_id)"
    Write-Host "Client Name: $($clientInfo.client_name)"
    Write-Host "Redirect URIs:"
    foreach ($uri in $clientInfo.redirect_uris) {
        Write-Host "  - $uri"
    }
    Write-Host "Grant Types:"
    foreach ($type in $clientInfo.grant_types) {
        Write-Host "  - $type"
    }
    Write-Host "Response Types:"
    foreach ($type in $clientInfo.response_types) {
        Write-Host "  - $type"
    }
    Write-Host "Scope: $($clientInfo.scope)"
    Write-Host "Skip Consent: $($clientInfo.skip_consent)"

} catch {
    Write-Error "Failed to verify client configuration: $($_.Exception.Message)"
    exit 1
}

# Test OAuth endpoints
Write-Step "Testing OAuth endpoints..."

# Test authorization endpoint
$authUrl = "http://localhost:4444/oauth2/auth?client_id=dev-client-id&response_type=code&scope=openid%20profile%20email&redirect_uri=http://localhost:3000/auth/callback&state=test-state"

try {
    $authResponse = Invoke-WebRequest -Uri $authUrl -Method GET -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
    if ($authResponse.StatusCode -eq 302 -or $authResponse.StatusCode -eq 200) {
        Write-Success "Authorization endpoint is working"
    } else {
        Write-Warning "Authorization endpoint may have issues (Status: $($authResponse.StatusCode))"
    }
} catch {
    if ($_.Exception.Response.StatusCode -eq 302) {
        Write-Success "Authorization endpoint is working (redirect response)"
    } else {
        Write-Warning "Authorization endpoint may have issues"
    }
}

# Test token endpoint (should return 400 without proper request)
try {
    $tokenResponse = Invoke-WebRequest -Uri "http://localhost:4444/oauth2/token" -Method POST -UseBasicParsing -ErrorAction SilentlyContinue
} catch {
    if ($_.Exception.Response.StatusCode -eq 400 -or $_.Exception.Response.StatusCode -eq 405) {
        Write-Success "Token endpoint is accessible"
    } else {
        Write-Warning "Token endpoint may have issues"
    }
}

# Test userinfo endpoint (should return 401 without token)
try {
    $userinfoResponse = Invoke-WebRequest -Uri "http://localhost:4444/userinfo" -Method GET -UseBasicParsing -ErrorAction SilentlyContinue
} catch {
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Success "Userinfo endpoint is accessible"
    } else {
        Write-Warning "Userinfo endpoint may have issues"
    }
}

Write-Step "OAuth Client Fix Complete!"
Write-Host "=========================="
Write-Success "OAuth client has been successfully configured"
Write-Host ""
Write-Host "🔗 You can now test the OAuth flow:"
Write-Host "   1. Open http://localhost:3000/auth/login"
Write-Host "   2. Click the OAuth login button"
Write-Host "   3. Complete the authorization flow"
Write-Host ""
Write-Host "🧪 Run tests to verify:"
Write-Host "   cd frontend && npm run test:e2e -- oauth-flow.spec.ts"
Write-Host ""
Write-Host "🔍 Debug information:"
Write-Host "   Authorization URL: $authUrl"
Write-Host "   Token URL: http://localhost:4444/oauth2/token"
Write-Host "   Userinfo URL: http://localhost:4444/userinfo"
Write-Host ""

Write-Success "OAuth client configuration fix completed successfully!"
