# Lifecontour - Backend

Python FastAPI backend for Lifecontour with PostgreSQL database, MCP protocol support, and integrations with Google Calendar, Google Contacts, and Immich.

## Quick Start

### Prerequisites

- Python 3.14+
- UV for dependency management
- PostgreSQL database
- Docker and Docker Compose (optional)
- **DejaVu Sans** (`sudo apt-get install fonts-dejavu-core` on Debian/Ubuntu, or
  the distribution equivalent) — the outdoor logbook PDF export draws its
  journal-type icon glyphs with it, because the built-in PDF fonts are
  WinAnsi-encoded and would render those codepoints as empty boxes. Without it
  the export still succeeds with plain text labels, but the glyph tests fail
  (in `tests/unit/journal/test_logbook_pdf_renderer.py`,
  `tests/integration/core/journal/services/test_logbook_pdf_renderer_integration.py`
  and `tests/integration/api/journals/test_logbook_export_api.py`). The Docker
  images install it via `docker/python-base/Dockerfile`.

### Development Setup

1. **Install dependencies:**
   ```bash
   uv pip install -e .[dev]
   ```

2. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```

4. **Start development server:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test types
pytest -m unit
pytest -m integration
pytest -m e2e
```

### Code Quality

```bash
# Linting
ruff check .
ruff check . --fix

# Formatting
black .

# Type checking
mypy .
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

## API Documentation

When running in development mode, API documentation is available at:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

## Architecture

The backend follows domain-driven design principles with clear separation of concerns:

- **Core Domains**: contacts, calendar, journal, photos
- **Integration Sub-Domains**: google, immich
- **Infrastructure**: database, logging, configuration
- **API Layer**: FastAPI controllers and DTOs

See [Architecture Documentation](../docs/architecture.md) for detailed information.
