# Technology Stack - Personal CRM & Journal System

This document outlines the technology choices optimized for AI assistant understanding and development ease.

## Backend Technology Stack

### Runtime and Language
- **Runtime**: Python 3.11+
- **Language**: Python with type hints
- **Dependency Management**: UV (modern, fast Python package manager)
- **Package Configuration**: pyproject.toml with UV

### Web Framework and API
- **Web Framework**: FastAPI (excellent AI assistant support, automatic docs)
- **API Standard**: JSON API specification compliance
- **API Documentation**: FastAPI automatic OpenAPI/Swagger generation
- **Request Validation**: Pydantic v2 for clear, explicit validation
- **Middleware**: FastAPI built-in CORS, custom rate limiting

### Database and Queries
- **Database**: PostgreSQL 15+ (production-ready, Docker-friendly)
- **Query Layer**: SQLAlchemy Core (explicit SQL, no ORM magic)
- **Migrations**: Alembic for clear, readable SQL migration files
- **Database Driver**: psycopg2-binary (simple, reliable)
- **Connection**: Direct SQLAlchemy connection (optimized for clarity)

### Authentication and Security
- **Authentication**: python-jose + passlib (simple, explicit patterns)
- **OAuth Integration**: google-auth for Google Calendar/Contacts
- **Session Management**: JWT tokens with FastAPI security
- **API Security**: FastAPI built-in security, custom rate limiting

### External Integrations
- **HTTP Client**: requests (simple, AI-friendly patterns)
- **Google APIs**: google-api-python-client (official SDK)
- **MCP Protocol**: Official Python MCP SDK
- **Immich Integration**: Direct REST API calls with requests
- **Search Engine**: MeiliSearch with official Python SDK (meilisearch-python)

### Search and Event Processing
- **Search Engine**: MeiliSearch 1.2+ (fast, typo-tolerant search)
- **Search Client**: meilisearch-python (official Python SDK)
- **Event Publishing**: Transactional outbox pattern with FastAPI background tasks
- **Event Storage**: PostgreSQL outbox table (same database as main data)

### Logging and Observability
- **Logging**: Python standard library logging (simple, clear)
- **Observability**: OpenTelemetry Python SDK
- **Monitoring**: Custom FastAPI middleware
- **Health Checks**: FastAPI health endpoints

### Testing Framework
- **Unit Testing**: pytest with pytest-asyncio
- **Test Coverage**: Focus on critical business logic
- **Mocking**: pytest-mock for external dependencies
- **Test Database**: PostgreSQL test database

## Frontend Technology Stack

### Framework and Language
- **Framework**: Next.js 14+ with React 18+ (clear separation from Python backend)
- **Language**: TypeScript with strict mode
- **Build Tool**: Next.js built-in
- **Package Manager**: pnpm (separate from backend UV setup)

### Styling and UI
- **Styling**: Tailwind CSS
- **UI Components**: shadcn/ui (excellent AI assistant support)
- **Icons**: Lucide React
- **Responsive Design**: Mobile-first with Tailwind

### State Management
- **State Management**: Zustand (simple, AI-friendly patterns)
- **Server State**: TanStack Query for API caching
- **Form State**: React Hook Form with Zod validation
- **Local Storage**: Zustand persist middleware

### Development Tools
- **Type Checking**: TypeScript strict mode
- **Linting**: ESLint (separate config from backend)
- **Formatting**: Prettier

## Project Structure (AI-Optimized)

### Clear Separation Architecture
```
personal-management-system/
├── backend/                      # Python FastAPI application
│   ├── app/
|   |   |── core/                 # Core Domain Logic
|   |   |   |── contacts/        # Contact Domain Logic
|   |   |   |   |── adapters/    # Interfaces with apis, sql, events, etc
|   |   |   |   |   |── api/     # External API clients
|   |   |   |   |   |── sql/     # Database repositories
|   |   |   |   |   |── events/  # Event publishing and receiving adapters
|   |   |   |   |── models/      # Domain models
|   |   |   |── calendar/        # Calendar Domain Logic
|   |   |   |── journal/         # Journal Domain Logic
|   |   |── infrastructure/      # Common code for Database, Events, etc.
│   │   ├── api/                 # FastAPI route handlers
│   │   |   ├── dtos/            # Pydantic models
│   │   ├── migrations/          # SQL queries and migrations
│   │   └── integrations/        # External Sub-Domains
│   │       ├── google/          # Google Integration Sub-Domain
│   │       └── immich/          # Immich Integration Sub-Domain
│   ├── tests/                    # pytest test suite
│   |   ├── unit/                 # Unit tests
│   │   ├── integration/          # Integration tests
│   │   └── e2e/                  # End-to-end tests
│   └── pyproject.toml            # UV dependencies
├── frontend/                     # Next.js TypeScript application
│   ├── src/
│   │   ├── app/                  # Next.js app router
│   │   ├── components/           # React components
│   │   ├── lib/                  # Utilities and API clients
│   │   └── types/                # TypeScript interfaces
│   ├── tests/                    # React Testing Library tests
│   └── package.json              # pnpm dependencies
|── docker-compose.yml            # Multi-container setup
|── docs/                         # All documentation
|   ├── architecture/             # Architecture documentation
|   ├── examples/                 # Code examples and patterns
|   ├── ai-guidelines.md          # AI assistant guidelines
|   ├── tasks.md                  # Task tracking and agile development
|   └── ...                       # Other documentation
```

### Container Architecture
- **Backend Container**: Python FastAPI with UV
- **Frontend Container**: Next.js with pnpm
- **Database Container**: PostgreSQL 15+
- **Search Container**: MeiliSearch 1.2+
- **Reverse Proxy**: nginx for routing

## Testing Strategy

### Backend Testing (Python)
- **Unit Tests**: pytest with clear, simple test patterns
- **Integration Tests**: pytest with PostgreSQL test database
- **API Tests**: FastAPI TestClient for endpoint testing
- **Mocking**: pytest-mock for external services

### Frontend Testing (TypeScript)
- **Component Tests**: React Testing Library
- **Integration Tests**: Next.js testing patterns
- **E2E Tests**: Playwright for critical user flows

## Development Tools

### Code Quality
- **Backend**: ruff (Python linting), black (formatting), mypy (type checking)
- **Frontend**: ESLint, Prettier, TypeScript strict mode
- **Separate Configs**: Independent linting setups for backend/frontend

### Development Setup
- **Backend**: UV for Python dependency management
- **Frontend**: pnpm for Node.js dependencies
- **Containers**: Docker Compose for local development
- **Hot Reload**: FastAPI auto-reload, Next.js hot reload

## Deployment Strategy

### Multi-Container Docker Setup
- **Backend**: Python FastAPI with UV dependencies
- **Frontend**: Next.js with pnpm dependencies
- **Database**: PostgreSQL 15+ with persistent volumes
- **Search**: MeiliSearch 1.2+ with persistent volumes
- **Proxy**: nginx for routing and SSL termination

### Development Environment
- **Local**: Docker Compose with hot reload
- **Testing**: Isolated containers with test databases
- **Production**: Container orchestration (Docker Compose or similar)

## Key AI Development Benefits

### Technology Stack Optimized for AI Assistants
| Component | Choice | AI Benefit |
|-----------|--------|------------|
| **Backend Language** | Python 3.11+ | Excellent AI assistant familiarity |
| **Backend Framework** | FastAPI | Clear patterns, automatic docs |
| **Database Queries** | SQLAlchemy Core | Explicit SQL, no ORM magic |
| **Frontend Framework** | Next.js + TypeScript | Well-established patterns |
| **UI Components** | shadcn/ui | Excellent AI support |
| **Package Managers** | UV (backend), pnpm (frontend) | Clear separation |
| **Database** | PostgreSQL | Production-ready, clear schemas |
| **Search Engine** | MeiliSearch | Fast, typo-tolerant, simple API |
| **Event Processing** | Outbox Pattern | Transactional safety, simple patterns |

### Core AI Benefits
1. **Clear Language Separation**: Python backend, TypeScript frontend
2. **Explicit Patterns**: No magic, everything is readable
3. **Simple Dependencies**: Standard libraries over complex abstractions
4. **Readable Code**: Optimized for understanding over performance
5. **Standard Conventions**: Well-known patterns AI assistants understand

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture
- [Domain Architecture](./domain-architecture.md) - Domain design patterns
- [Database Design](./database-design.md) - PostgreSQL schema design
- [Deployment Guide](./deployment-guide.md) - Docker deployment setup
