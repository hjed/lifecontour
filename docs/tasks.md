# Personal CRM & Journal System - Task Overview

## Project Overview
A comprehensive personal management system with Python FastAPI backend, Next.js frontend, and AI integration via MCP protocol. Integrates personal data from multiple sources (Google Calendar/Contacts, Immich photos, Strava activities, financial data) with both web interface and AI assistant capabilities.

## Technology Stack
- **Backend:** Python 3.11+ with FastAPI, PostgreSQL, Dishka dependency injection
- **Frontend:** Next.js with React, shadcn/ui components, Tailwind CSS
- **AI Integration:** MCP (Model Context Protocol) with FastMCP v2 framework
- **Search:** MeiliSearch with event-driven indexing
- **Background Processing:** ARQ task queue with Redis
- **Testing:** pytest (backend), Jest/React Testing Library (frontend), Playwright (e2e)
- **Deployment:** Docker with nginx proxy support

## Development Principles
- **Test-First Development:** Write tests before implementation - no exceptions
- **Reviewable PRs:** Each task creates PRs with max 10 files changed
- **Quality Gates:** All tests, linting, and type checking must pass
- **Architecture Consistency:** Follow established patterns (Dishka DI, ARQ workers, etc.)
- **AI-Optimized:** Design for AI assistant understanding and integration

The [architecture document](./architecture.md) provides a high-level overview of the system architecture and navigation.

The [AI guidelines](./ai-guidelines.md) provide essential information for AI assistants working on the project. The AI Guidelines MUST be followed at all times. NO EXCEPTIONS.

Integrations MUST follow the integration architecture specified in the [integration architecture document](./architecture/integration-architecture.md). Including using the event based architecture.

## Task Organization
Tasks are organized into **feature iterations** that deliver end-to-end value incrementally. Each iteration is documented in detail in separate files for better organization and navigation.

---

## Iterations Overview

### [Iteration 1: Basic Contact Management (MVP)](./tasks/iteration-1-basic-contact-management.md)
**Status:** ✅ COMPLETED
**Goal:** Establish core contact management functionality with search capabilities and MCP integration

**Key Deliverables:**
- Python FastAPI backend with PostgreSQL database
- Next.js frontend with shadcn/ui components
- MeiliSearch-powered search capabilities
- MCP (Model Context Protocol) integration for AI assistants
- Comprehensive testing suite (pytest, Jest, Playwright)
- Docker-based development environment

**Architecture Established:**
- SQLAlchemy Core with explicit SQL queries
- Simple dependency injection (later upgraded to Dishka)
- Event-driven MeiliSearch indexing via transactional outbox pattern
- OAuth2 authentication with configurable providers

### [Iteration 1.5: Enhanced Layout & Navigation (MVP Usability)](./tasks/iteration-1.5-enhanced-layout-navigation.md)
**Status:** ✅ COMPLETED
**Goal:** Improve user experience with modern navigation patterns and contact filtering

**Key Deliverables:**
- Redesigned header with prominent search functionality
- Hierarchical sidebar navigation with collapsible sections
- Contact filtering and favourites functionality
- Tag-based grouping and organization
- Responsive design for mobile and desktop
- 295 tests passing with 100% success rate

**Quality Improvements:**
- Extracted reusable components (`ContactCard`, `ContactList`) and hooks (`useDisplayContacts`)
- Fixed Playwright e2e tests with proper `waitForSelector` calls
- Improved code quality and maintainability

### [Iteration 2: Integration Architecture Foundation](./tasks/iteration-2-integration-architecture.md)
**Status:** 🟡 IN PROGRESS (60% complete)
**Goal:** Establish robust integration architecture with Google Contacts sync

**Key Deliverables:**
- Dishka dependency injection framework migration
- ARQ task queue with Redis for background processing
- Google Contacts bidirectional synchronization (60% complete)
- Isolated worker architecture for scalability
- Production resilience patterns (idempotency, retry logic, monitoring)

**Current Progress:**
- ✅ Integration foundation with ARQ and Redis
- ✅ Google API client with automatic token refresh
- ✅ Data modeling and transformation
- ✅ Idempotent persistence and incremental sync logic
- 🟡 ARQ worker implementation with Dishka integration (pending)
- 🟡 Two-way sync and conflict resolution (pending)

### [Iteration 3: Extended Integrations](./tasks/iteration-3-extended-integrations.md)
**Status:** 🟡 PLANNED
**Goal:** Expand integration capabilities with Immich photos, Strava activities, and financial data

**Planned Integrations:**
- **Immich Integration:** Photo service with person-to-contact matching
- **Strava Integration:** Activity tracking with automatic journal entries
- **Firefly III Integration:** Financial data with transaction linking
- **Enhanced MCP Tools:** Cross-integration search and management

**Architecture Benefits:**
- Leverages integration patterns established in Iteration 2
- Unified integration management dashboard
- Cross-integration analytics and insights

### [Iteration 4: Journal System](./tasks/iteration-4-journal-system.md)
**Status:** 🟡 PLANNED
**Goal:** Build comprehensive journal system with integration-powered content

**Key Features:**
- Rich text editor with mood tracking and sentiment analysis
- Automatic journal entries from Strava activities and other integrations
- Photo album linking and visual storytelling
- AI-powered insights and writing assistance
- Advanced search across journal content with MeiliSearch
- MCP tools for AI-assisted journaling and reflection

### [Iteration 5: Calendar Integration](./tasks/iteration-5-calendar-integration.md)
**Status:** 🟡 PLANNED
**Goal:** Integrate Google Calendar with event-based journaling and meeting preparation

**Key Features:**
- Google Calendar bidirectional synchronization
- Event-based journal entry automation
- Meeting preparation with contact and context integration
- Calendar analytics and scheduling insights
- Time-based pattern recognition across all personal data
- MCP tools for AI-assisted scheduling and meeting management

### [Iteration 6: Advanced Features & Analytics](./tasks/iteration-6-advanced-features.md)
**Status:** 🟡 PLANNED
**Goal:** Deliver advanced analytics, AI insights, and comprehensive personal data intelligence

**Key Features:**
- Advanced analytics across all integrated data sources
- AI-powered life pattern recognition and insights
- Comprehensive testing and quality assurance (80%+ coverage)
- Performance optimization and scalability improvements
- Advanced security and privacy features
- Future protocol support and extensibility

---

## Current Status & Next Steps

**Immediate Priority:** Complete Iteration 2 (Integration Architecture Foundation)
- Finish Google Contacts integration (ARQ worker + two-way sync)
- Complete Dishka migration for entire application
- Implement production resilience patterns
- Build integration management UI

**Development Guidelines:**
- Each task creates reviewable PRs (max 10 files changed)
- All tests, linting, and type checking must pass before completion
- Follow established architecture patterns (Dishka DI, ARQ workers, FastMCP v2)
- Maintain comprehensive test coverage across all layers

**Quality Standards:**
- Test-first development approach
- Real database testing with Docker PostgreSQL
- Comprehensive error handling and monitoring
- Security-first design with encrypted credential storage

For detailed task breakdowns, acceptance criteria, and implementation notes, see the individual iteration files linked above.
