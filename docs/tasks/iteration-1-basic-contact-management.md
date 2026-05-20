# Iteration 1: Basic Contact Management (MVP)

**Status:** ✅ COMPLETED
**Dependencies:** None
**Goal:** Establish core contact management functionality with search capabilities and MCP integration

## Overview

This iteration delivers the foundational contact management system with:
- Python FastAPI backend with PostgreSQL database
- Next.js frontend with shadcn/ui components
- MeiliSearch-powered search capabilities
- MCP (Model Context Protocol) integration for AI assistants
- Comprehensive testing suite (pytest, Jest, Playwright)
- Docker-based development environment

## Tasks

### ITER1-001: Project Foundation 🟡 ✅ COMPLETED
**Description:** Set up project foundation with clear backend/frontend separation
**PR Size:** ~15 files (initial project setup)

**Acceptance Criteria:**
- [x] Initialize Python backend with UV and pyproject.toml
- [x] Set up FastAPI with Python 3.14+ and type hints
- [x] Configure PostgreSQL database with Docker Compose
- [x] Set up Python linting (ruff), formatting (black), type checking (mypy)
- [x] Initialize Next.js frontend with TypeScript and pnpm
- [x] Configure separate ESLint/Prettier for frontend
- [x] Create clear project structure (backend/, frontend/, docker-compose.yml)
- [x] Set up SQLAlchemy Core with explicit SQL queries
- [x] Configure Alembic for database migrations
- [x] Set up Python standard library logging
- [x] Configure nginx proxy support
- [x] Set up Tailwind CSS and shadcn/ui for frontend
- [x] Configure Australian English localisation (en-AU)
- [x] Set up pytest for backend testing
- [x] Configure React Testing Library for frontend testing
- [x] Set up Playwright for end-to-end testing
- [x] Create Docker containers for backend, frontend, database
- [x] Add development scripts and documentation

**Final Status:** All tests passing, all linting passing, all type checking passing. Project foundation complete.

### ITER1-002: Contacts Domain Core 🟡 ✅ COMPLETED
**Description:** Build contacts domain with structured tags and contact methods support
**PR Size:** ~8 files (domain models, repositories, services, tests)

**Acceptance Criteria:**
- [x] Create PostgreSQL schema (contacts, contact_methods, contact_addresses, contact_notes, tags, contact_tags, contact_history tables)
- [x] Write explicit SQL queries using SQLAlchemy Core text() with proper joins
- [x] Implement Contact, Tag, ContactMethod, ContactAddress, ContactNote Pydantic models for validation
- [x] Create domain entities with business logic
- [x] Implement repository interfaces with connection injection
- [x] Create ContactService with dependency injection and transaction management
- [x] Implement simple dependency injection container with constructor injection pattern
- [x] Add comprehensive error handling with custom exceptions and HTTP status codes
- [x] Implement business rule validation (email uniqueness, tag limits, primary methods)
- [x] Set up contact history tracking for all changes
- [x] Create domain events (ContactCreated, ContactUpdated, TagAssigned, etc.)
- [x] Set up Alembic database migrations (single migration for all tables)
- [x] Write pytest unit tests for domain logic (no database dependencies)
- [x] Add database seed data for development and e2e testing

**Final Status:** All domain logic implemented with 112 unit tests and 53 integration tests passing. ContactMethod.method_type converted to type-safe enum.

### ITER1-003: Contacts REST API with Search 🟡 ✅ COMPLETED
**Description:** Create JSON API compliant FastAPI endpoints with MeiliSearch integration
**PR Size:** ~10 files (API controllers, search integration, tests)

**Acceptance Criteria:**
- [x] Set up MeiliSearch Docker container and Python SDK integration
- [x] Implement transactional outbox pattern for reliable event publishing
- [x] Create OutboxEventPublisher implementing existing ContactEventPublisher interface
- [x] Set up FastAPI background task for outbox processing (every 10 seconds)
- [x] Implement OAuth2 authentication using Authlib with configurable providers
- [x] Create OAuth endpoints (authorize/callback/logout) and session validation dependency
- [x] Configure OAuth providers (GitHub, Microsoft, Discord, generic OAuth2) via config file
- [x] Create FastAPI ContactController with automatic OpenAPI docs
- [x] Implement CRUD operations (GET, POST, PUT, DELETE) with proper error handling
- [x] Add contact search endpoints using MeiliSearch (/api/contacts/search)
- [x] Add global search endpoint for contacts (/api/search)
- [x] Add tag management endpoints (assign/remove tags)
- [x] Implement comprehensive input validation using Pydantic models
- [x] Configure CORS for frontend integration
- [x] Implement event-driven MeiliSearch indexing via outbox pattern
- [x] Add search features: typo tolerance, highlighting, faceted search, pagination
- [x] Add comprehensive pytest integration tests for all endpoints including search
- [x] Generate automatic Swagger documentation
- [x] Add MeiliSearch health checks to system health endpoint

**Final Status:** All REST API endpoints implemented with comprehensive search capabilities, OAuth2 authentication, event-driven MeiliSearch indexing, and full test coverage.

### ITER1-004: Contact UI with Search 🔴 ✅ COMPLETED
**Description:** Create Next.js frontend for contact management with search capabilities
**PR Size:** ~12 files (React components, API client, tests)

**Acceptance Criteria:**
- [x] Set up Next.js with TypeScript, Tailwind CSS, and shadcn/ui
- [x] Configure API client for FastAPI backend communication
- [x] Implement Australian English interface (en-AU locale, DD/MM/YYYY dates)
- [x] Create contact list view with search and filtering capabilities
- [x] Implement contact creation and editing forms with validation
- [x] Implement responsive design with mobile-first approach
- [x] Add error handling and loading states
- [x] Write React Testing Library tests for components (69 Jest tests passing)
- [x] Add comprehensive end-to-end tests with Playwright
- [x] Deploy working MVP with Docker Compose including MeiliSearch

**Final Status:** ✅ MVP deployment complete! Full stack running successfully with Docker Compose. All core contact management features working with comprehensive testing suite (69 Jest tests + Playwright e2e tests).

### ITER1-005: Contact MCP Tools 🟡 ✅ COMPLETED
**Description:** Implement MCP (Model Context Protocol) server foundation and contact tools
**PR Size:** ~6 files (MCP server, tools, tests)

**Acceptance Criteria:**
- [x] Set up MCP server framework and protocol implementation
- [x] Implement basic MCP message handling and connection management
- [x] Add authentication and security for MCP connections
- [x] Create MCP tool registration system
- [x] Implement contact search, creation, and management tools using MeiliSearch
- [x] Document MCP server setup and configuration
- [x] Implement health checks for MCP server
- [x] Create MCP client test suite for contact tools
- [x] Add comprehensive MCP tool documentation

**Final Status:** MCP server foundation complete with comprehensive contact tools including search, creation, and management. Tools implemented: get_contact, search_contacts, global_search, create_contact, list_contacts.

## Architecture Notes

- **Dependency Injection:** Uses simple constructor injection pattern (later upgraded to Dishka in Iteration 2)
- **Database:** SQLAlchemy Core with explicit SQL queries for transparency
- **Search:** Event-driven MeiliSearch indexing via transactional outbox pattern
- **Authentication:** OAuth2 with configurable providers (GitHub, Microsoft, Discord)
- **Testing:** Three-layer testing (unit, integration, e2e) with real PostgreSQL for integration tests
- **MCP Integration:** Custom MCP server implementation (later upgraded to FastMCP v2)

## Deployment

The iteration results in a fully functional MVP deployed via Docker Compose:
- Backend (FastAPI): http://localhost:8000
- Frontend (Next.js): http://localhost:3000
- Database (PostgreSQL): localhost:5432
- Search (MeiliSearch): http://localhost:7700
- Observability (Jaeger): http://localhost:16686

## Next Steps

This iteration provides the foundation for:
- Enhanced UI/UX improvements (Iteration 1.5)
- Integration architecture for external services (Iteration 2)
- Additional domains (journal, calendar, photos)
