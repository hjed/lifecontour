# Quality check script for backend code (PowerShell version)
# Run this before every commit to ensure code quality

$ErrorActionPreference = "Stop"

Write-Host "🔍 Running quality checks..." -ForegroundColor Cyan

Write-Host "📋 Step 1: Ruff linting check..." -ForegroundColor Yellow
uv run ruff check .

Write-Host "🎨 Step 2: Ruff formatting check..." -ForegroundColor Yellow
uv run ruff format --check .

Write-Host "🧪 Step 3: Running unit tests..." -ForegroundColor Yellow
uv run python -m pytest tests/unit/ -v

Write-Host "🔗 Step 4: Running integration tests..." -ForegroundColor Yellow
uv run python -m pytest tests/integration/ -v

Write-Host "✅ All quality checks passed!" -ForegroundColor Green
Write-Host "🚀 Ready to commit and push!" -ForegroundColor Green
