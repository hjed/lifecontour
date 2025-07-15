#!/bin/bash
# Quality check script for backend code
# Run this before every commit to ensure code quality

set -e  # Exit on any error

echo "🔍 Running quality checks..."

echo "📋 Step 1: Ruff linting check..."
uv run ruff check .

echo "🎨 Step 2: Ruff formatting check..."
uv run ruff format --check .

echo "🔍 Step 3: MyPy type checking..."
uv run mypy app/

echo "🧪 Step 4: Running unit tests..."
uv run python -m pytest tests/unit/ -v

echo "🔗 Step 5: Running integration tests..."
uv run python -m pytest tests/integration/ -v

echo "✅ All quality checks passed!"
echo "🚀 Ready to commit and push!"
