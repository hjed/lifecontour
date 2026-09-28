# Personal CRM & Journal System
Contact and Life Management in the Age of AI.

A personal relationship management and journaling system with AI integration through the MCP (Model Context Protocol). Built with Python FastAPI backend, Next.js frontend, and PostgreSQL database.

## 🚀 Quick Start

### Prerequisites

- Python 3.14+ with [UV](https://github.com/astral-sh/uv) for dependency management
- Node.js 26+ with [pnpm](https://pnpm.io/) 11+ for frontend dependencies (use `nvm use` to activate — see `.nvmrc`)
- Docker and Docker Compose
- PostgreSQL database

### Development Setup

1. **Clone and setup:**
   ```bash
   git clone <repository-url>
   cd personal-management-system
   ./scripts/dev.sh setup
   ```

2. **Start the database:**
   ```bash
   docker-compose up database -d
   ```

3. **Run database migrations:**
   ```bash
   cd backend
   alembic upgrade head
   cd ..
   ```

4. **Start development servers:**
   ```bash
   ./scripts/dev.sh start
   ```

5. **Access the application:**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Documentation: http://localhost:8000/api/docs

### Docker Development Environment

For a complete development environment with all services:

```bash
# Start complete Docker development environment (default dev profile)
docker compose up

# Stop Docker development environment
docker compose down

# Rebuild Docker images (useful when dependencies change)
docker compose build --no-cache

# Rebuild specific service only
docker compose build --no-cache backend
```

For detailed Docker Compose setup and profiles, see [Docker Compose Unified Setup](docs/DOCKER_COMPOSE_UNIFIED.md).

### Testing with Docker

```bash
# Run tests with test profile
docker compose --profile test --env-file .env.test up

# Run backend integration tests only
docker compose --profile test-backend up

# Clean up this worktree's test environment (all profiles, volumes and networks)
python3 scripts/teardown_workspace.py

# Same, for a worktree that has already been deleted
python3 scripts/teardown_workspace.py /path/to/removed/worktree
```

Each worktree runs its Docker stack under its own compose project name
(`pms_test_<N>`, derived from the worktree path by `scripts/workspace_env.py`),
so several checkouts can run tests side by side. `scripts/teardown_workspace.py`
removes everything belonging to one such project — it is safe to call from a
worktree-cleanup hook, and leaves other worktrees and the shared
`personal-management` network alone. `--prune-stale` sweeps every workspace
project whose worktree no longer exists.

### Production Deployment

```bash
# Start all services with nginx proxy
docker compose --profile prod --env-file .env.prod up -d

# Access via nginx proxy
# Frontend: http://localhost
# Backend API: http://localhost/api
```

## 🏗️ Architecture

### Technology Stack

- **Backend**: Python 3.14+ with FastAPI, SQLAlchemy Core, PostgreSQL
- **Frontend**: Next.js 14 with TypeScript, Tailwind CSS, shadcn/ui
- **Database**: PostgreSQL with Alembic migrations
- **Deployment**: Docker with nginx reverse proxy
- **Testing**: pytest (backend), Jest + React Testing Library (frontend), Playwright (e2e)

### Project Structure

```
personal-management-system/
├── backend/                 # Python FastAPI application
│   ├── app/
│   │   ├── core/           # Domain logic (contacts, calendar, journal)
│   │   ├── infrastructure/ # Database, logging, configuration
│   │   ├── api/           # FastAPI controllers and DTOs
│   │   └── integrations/  # External services (Google, Immich)
│   ├── tests/             # pytest test suite
│   └── pyproject.toml     # UV dependencies
├── frontend/              # Next.js TypeScript application
│   ├── src/
│   │   ├── app/          # Next.js app router
│   │   ├── components/   # React components (shadcn/ui)
│   │   └── lib/          # Utilities and API clients
│   ├── tests/            # Jest and Playwright tests
│   └── package.json      # pnpm dependencies
├── docker/               # Docker configurations
├── docs/                 # Documentation
└── docker-compose.yml    # Multi-container setup
```

## 📋 Features

### Current (Iteration 1 - Foundation)
- ✅ **Project Foundation**: Python FastAPI + Next.js with full development setup
- ✅ **Database**: PostgreSQL with Alembic migrations
- ✅ **Testing**: Comprehensive test setup (pytest, Jest, Playwright)
- ✅ **Development Tools**: Linting, formatting, type checking
- ✅ **Docker**: Multi-container setup with nginx proxy

### Planned Features
- **Contacts Management**: Personal and professional contacts with tags
- **Google Integration**: Bidirectional sync with Google Contacts and Calendar
- **Journal System**: Personal journaling with mood tracking and album linking
- **Photo Integration**: Immich integration with person-to-contact matching
- **AI Integration**: MCP protocol support for AI assistant access
- **Advanced Features**: CardDAV/CalDAV protocols, Home Assistant integration

## 🧪 Development

### Docker Image Management

When working with Docker, you may need to rebuild images to pick up changes:

```bash
# Rebuild all development images (when dependencies change)
./scripts/dev.sh docker-rebuild

# Rebuild specific service (faster for single service changes)
./scripts/dev.sh docker-rebuild-service backend-dev

# View Docker service status
./scripts/dev.sh docker-status
```

**When to rebuild:**
- After changing `pyproject.toml` or `package.json` dependencies
- After modifying Dockerfile configurations
- When experiencing issues with outdated cached layers
- After pulling changes that affect Docker setup

### Running Tests

```bash
# All tests
./scripts/dev.sh test

# Backend only
cd backend && pytest

# Frontend only
cd frontend && pnpm test

# End-to-end tests
cd frontend && pnpm test:e2e
```

### Code Quality

```bash
# Check all quality standards (same as CI)
./scripts/dev.sh lint

# Auto-fix linting issues
./scripts/dev.sh lint-fix

# Run pre-commit hooks manually
./scripts/dev.sh precommit
```

See [Code Quality Standards](docs/code-quality-standards.md) for detailed information about our consolidated linting approach.

### Database Operations

```bash
cd backend

# Create migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## 📚 Documentation

### Core Documentation
- **[Architecture Overview](docs/architecture.md)** - System design and patterns
- **[AI Guidelines](AGENTS.md)** - Development guidelines for AI assistants
- **[Contributing](CONTRIBUTING.md)** - How to propose and submit a change
- **[Task Management](docs/tasks.md)** - Agile development roadmap

### Development Guides
- **[Contacts Product Specification](docs/product-specifications/contacts-product-specification.md)** - Target product behaviour for the contacts improvement stream
- **[Journals Product Specification](docs/product-specifications/journals-product-specification.md)** - Target product behaviour for the journals improvement stream
- **[Entity Ownership Product Specification](docs/product-specifications/entity-ownership-product-specification.md)** - Target behaviour for per-user ownership of contacts, tags and integration links
- **[Code Quality Standards](docs/code-quality-standards.md)** - Linting, formatting, and testing standards
- **[Testing Strategy](docs/architecture/testing-strategy.md)** - Comprehensive testing patterns and fixture-based E2E testing
- **[E2E Testing Guide](frontend/tests/e2e/FIXTURE_SYSTEM_GUIDE.md)** - Advanced fixture system with real OAuth authentication
- **[CI/CD Setup](docs/ci-cd-setup.md)** - Continuous integration and deployment
- **[MCP Setup](docs/mcp-setup.md)** - Model Context Protocol integration

### Troubleshooting
- **[Troubleshooting Index](docs/troubleshooting/README.md)** - Complete troubleshooting guide index
- **[Docker Development](docs/troubleshooting/docker-development.md)** - Complete Docker setup and usage
- **[Docker Fixes](docs/troubleshooting/docker-fixes.md)** - Common Docker issues and solutions
- **[CI Integration Tests](docs/troubleshooting/ci-integration-tests-fix.md)** - Backend CI test configuration
- **[Frontend CI Fixes](docs/troubleshooting/frontend-ci-fixes.md)** - Frontend CI and testing issues

### Component Documentation
- **[Backend README](backend/README.md)** - Python FastAPI backend details
- **[Frontend README](frontend/README.md)** - Next.js frontend details

## 🔧 Configuration

### Environment Variables

**Backend** (`.env`):
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/personal_management
DEBUG=true
SECRET_KEY=your-secret-key
GOOGLE_CLIENT_ID=your-google-client-id
IMMICH_BASE_URL=http://your-immich-instance
```

**Frontend** (`.env.local`):
```bash
BACKEND_URL=http://localhost:8001
NODE_ENV=development
```

## 🤝 Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first: open an issue to discuss
the change, keep pull requests to at most 500 changed lines, and disclose AI assistance.
Contributors sign the [Contributor License Agreement](CLA.md) on their first pull request.
Coding agents follow [AGENTS.md](AGENTS.md). See [tasks.md](docs/tasks.md) for the current roadmap.

## 📄 License

Copyright (C) 2025–2026 Harry J E Day

This project is licensed under the GNU Affero General Public License v3.0 or later
(SPDX: `AGPL-3.0-or-later`). See [LICENSE](LICENSE) for the full text, and
[LICENSE-EXCEPTIONS.md](LICENSE-EXCEPTIONS.md) for the additional permission covering
react-leaflet. Third-party dependency licences are recorded in the
[licence audit](docs/licensing/third-party-licences.md).

The project name and logo are not covered by that licence. See [TRADEMARKS.md](TRADEMARKS.md).
To report a vulnerability, see [SECURITY.md](SECURITY.md), and for community standards see
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

**Personal Management System** - Centralize your personal data with AI integration

