# Personal CRM & Journal System - Architecture Overview

## System Overview

The Personal CRM & Journal System is a Python FastAPI backend with Next.js frontend designed to centralize personal relationship management and journaling with intelligent AI integration through the MCP (Model Context Protocol).

### Core Objectives
- **Unified Personal Data**: Centralize contacts, calendar events, journal entries, and photos
- **AI Integration**: Provide rich context to AI assistants through MCP protocol
- **Multi-Interface**: Support both programmatic (MCP) and human (web) interfaces
- **Privacy-First**: PostgreSQL storage with controlled external integrations
- **Standard Protocols**: JSON API for REST, CardDAV/CalDAV for interoperability
- **Smart Album Integration**: Link Immich albums to journal entries and events
- **Name-Based Matching**: Link contacts to Immich people by name or manual confirmation
- **Global Search**: Fast, typo-tolerant search across all entities with MeiliSearch
- **Transactional Events**: Reliable event publishing with outbox pattern
- **Event-Driven History**: Field-level activity history for contacts and journals derived as a read-model projection of domain events (see the [Activity History Product Specification](./product-specifications/activity-history-product-specification.md))
- **Clear Language Separation**: Python backend, TypeScript frontend for AI clarity
- **Agile Development**: Feature-complete iterations delivering incremental value
- **Proxy-Ready**: Support deployment behind nginx reverse proxy
- **AI-Optimized**: Explicit patterns and readable code over performance optimization
- **Inegrations**: Designed to support integrations with other services and protocols for best in class experience with integrations

## Architecture Documentation

This document provides a high-level overview of the system architecture. For detailed information, refer to the following documents:

## Product Specifications

These product specifications describe the target product behaviour that active implementation and iteration plans should align to:

- **[Contacts Product Specification](./product-specifications/contacts-product-specification.md)** - target behaviour for contact organisation, sync, search, summaries, and MCP parity
- **[Journals Product Specification](./product-specifications/journals-product-specification.md)** - target behaviour for journal sync, merge, hierarchy, list navigation, summaries, and MCP parity
- **[Activity History Product Specification](./product-specifications/activity-history-product-specification.md)** - unified, event-driven field-level history across contacts and journals, with provenance and MCP parity
- **[Home Dashboard & Tasks Product Specification](./product-specifications/home-dashboard-and-tasks-product-specification.md)** - target behaviour for the journal-anchored Tasks entity, the home dashboard, and the extended AI daily summary

### 📋 **[Domain Architecture](./architecture/domain-architecture.md)**
Detailed domain-driven design, component architecture, and project structure including:
- Domain layer design and business logic
- Adapter patterns and external integrations
- Project structure and architectural principles
- Cross-domain operations and event handling

### 🗄️ **[Database Design](./architecture/database-design.md)**
Complete database schema, relationships, and data layer implementation:
- PostgreSQL database schema and table structures
- Indexing strategies and query optimization
- Data relationships and JSON field structures
- Alembic migrations and backup strategies

### 🛠️ **[Technology Stack](./architecture/technology-stack.md)**
Technology choices, implementation details, and development tools:
- Backend and frontend technology selections
- High-level testing strategy and quality assurance
- External APIs and library integrations
- Development tools and configuration

### 🧪 **[Testing Strategy](./architecture/testing-strategy.md)**
Comprehensive testing patterns and implementation guidelines:
- Backend testing with pytest and Docker PostgreSQL
- Frontend testing with React Testing Library and Playwright
- Integration testing patterns and test organization
- Mock utilities and test data factories

### 🔌 **[API Design](./architecture/api-design.md)**
REST and MCP API implementation patterns and guidelines:
- FastAPI REST API design with JSON API compliance
- MCP tool structure and server implementation
- Input validation and error handling patterns
- Authentication and pagination guidelines

### 🎨 **[Frontend Design](./architecture/frontend-design.md)**
Component patterns and UI implementation guidelines:
- shadcn/ui component structure and accessibility
- Form validation with React Hook Form and Zod
- Responsive design and Tailwind CSS patterns
- Australian localization and performance optimization

### 🚀 **[Deployment Guide](./architecture/deployment-guide.md)**
Infrastructure setup, containerization, and operational procedures:
- Docker configuration and multi-stage builds
- Nginx proxy setup and SSL configuration
- Observability, monitoring, and health checks
- CI/CD pipeline and backup strategies

### 🔒 **[Security & Performance](./architecture/security-performance.md)**
Security considerations and performance optimization:
- Authentication, authorization, and data protection
- Performance optimization and caching strategies
- Monitoring, alerting, and operational security
- Compliance and privacy considerations

### 🔗 **[Integration Architecture](./architecture/integration-architecture.md)**
External service integration patterns and implementation:
- Google Contacts, Immich, Strava, Firefly III integrations
- Isolated Worker Architecture with dependency separation
- ARQ task queue system with Redis
- Sync metadata and conflict resolution patterns

### 📔 **[Journal System Specification](./journal-system-specification.md)**
Comprehensive journal system design and requirements:
- Core journal domain model with flexible type system
- 15 journal types (NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM, FITNESS, OUTDOOR_ACTIVITY, and activity subtypes)
- Hierarchical organization with parent-child relationships
- Integration with Strava, Google Calendar, and Immich
- Route tracking and activity analytics
- Frontend components with inline editing and visual organization

### 🔮 **[Future Roadmap](./architecture/future-roadmap.md)**
Future features, extensibility plans, and long-term vision:
- Custom field support
- Protocol extensions (CardDAV/CalDAV)
- Advanced AI features and machine learning
- Mobile support

## High-Level Architecture (Domain-Driven with Integration Sub-Domains)

```
                    ┌─────────────────────────────────────┐
                    │           Client Interfaces         │
                    │  ┌─────────────┐ ┌─────────────────┐ │
                    │  │MCP Protocol │ │  Web Interface  │ │
                    │  │(AI Clients) │ │   (Next.js)     │ │
                    │  └─────────────┘ └─────────────────┘ │
                    └─────────────────┬───────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                  API Layer                   │
              │  ┌─────────────────┐ │ ┌─────────────────────┐ │
              │  │   MCP Server    │ │ │   FastAPI Server    │ │
              │  │  (Python SDK)   │ │ │   (JSON API)        │ │
              │  │                 │ │ │   (Nginx Proxy      │ │
              │  │                 │ │ │    Compatible)      │ │
              │  └─────────────────┘ │ └─────────────────────┘ │
              └─────────────────────┬┴─────────────────────────┘
                                    │
    ┌─────────────────────────────────────────────────────────────────┐
    │                     Core Domain Layer                           │
    │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐  │
    │  │  Contacts   │ │  Calendar   │ │   Journal   │ │  Photos   │  │
    │  │   Domain    │ │   Domain    │ │   Domain    │ │  Domain   │  │
    │  │             │ │             │ │             │ │           │  │
    │  │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │ │┌────────┐ │  │
    │  │ │Business │ │ │ │Business │ │ │ │Business │ │ ││Business│ │  │
    │  │ │ Logic   │ │ │ │ Logic   │ │ │ │ Logic   │ │ ││ Logic  │ │  │
    │  │ │+ Events │ │ │ │+ Events │ │ │ │+ Events │ │ ││+ Events│ │  │
    │  │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │└────────┘ │  │
    │  │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │ │┌────────┐ │  │
    │  │ │Adapters │ │ │ │Adapters │ │ │ │Adapters │ │ ││Adapters│ │  │
    │  │ │(SQL,etc)│ │ │ │(SQL,etc)│ │ │ │(SQL,etc)│ │ ││(SQL,etc)││ │
    │  │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │└────────┘ │  │
    │  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘  │
    └─────────────────────────────────────────────────────────────────┘
                                    │
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Integration Domain                           │
    │  ┌─────────────────────────────────────────────────────────────┐ │
    │  │                  Shared Components                          │ │
    │  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐ │ │
    │  │  │SyncMetadata │ │ExternalRef  │ │    ARQ Task Queue       │ │ │
    │  │  │   Models    │ │   Models    │ │     (Redis-backed)      │ │ │
    │  │  └─────────────┘ └─────────────┘ └─────────────────────────┘ │ │
    │  └─────────────────────────────────────────────────────────────┘ │
    │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │
    │  │   Google    │ │   Immich    │ │   Strava    │ │ Firefly III │ │
    │  │ Integration │ │ Integration │ │ Integration │ │ Integration │ │
    │  │             │ │             │ │             │ │             │ │
    │  │┌───────────┐│ │┌───────────┐│ │┌───────────┐│ │┌───────────┐│ │
    │  ││Service    ││ ││Service    ││ ││Service    ││ ││Service    ││ │
    │  ││API Client ││ ││API Client ││ ││API Client ││ ││API Client ││ │
    │  ││Tasks      ││ ││Tasks      ││ ││Tasks      ││ ││Tasks      ││ │
    │  │└───────────┘│ │└───────────┘│ │└───────────┘│ │└───────────┘│ │
    │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
                                    │
    ┌─────────────────────────────────────────────────────────────────┐
    │                Background Worker Processes                      │
    │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │
    │  │   Google    │ │   Immich    │ │   Strava    │ │ Firefly III │ │
    │  │   Worker    │ │   Worker    │ │   Worker    │ │   Worker    │ │
    │  │             │ │             │ │             │ │             │ │
    │  │┌───────────┐│ │┌───────────┐│ │┌───────────┐│ │┌───────────┐│ │
    │  ││Isolated   ││ ││Isolated   ││ ││Isolated   ││ ││Isolated   ││ │
    │  ││Dependencies││ ││Dependencies││ ││Dependencies││ ││Dependencies││ │
    │  ││ARQ Tasks  ││ ││ARQ Tasks  ││ ││ARQ Tasks  ││ ││ARQ Tasks  ││ │
    │  │└───────────┘│ │└───────────┘│ │└───────────┘│ │└───────────┘│ │
    │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
                                    │
    ┌─────────────────────────────────────────────────────────────────┐
    │                     Data & Infrastructure Layer                 │
    │  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐ │
    │  │   PostgreSQL    │ │     Redis       │ │    MeiliSearch      │ │
    │  │                 │ │                 │ │                     │ │
    │  │ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────────┐ │ │
    │  │ │Main Tables  │ │ │ │ARQ Task     │ │ │ │Search Indexes   │ │ │
    │  │ │Outbox Table │ │ │ │Queue        │ │ │ │- contacts_index │ │ │
    │  │ │Event Store  │ │ │ │Integration  │ │ │ │- global_search  │ │ │
    │  │ │Sync Metadata│ │ │ │Job State    │ │ │ │- journal_index  │ │ │
    │  │ └─────────────┘ │ │ └─────────────┘ │ │ │- calendar_index │ │ │
    │  └─────────────────┘ └─────────────────┘ │ └─────────────────┘ │ │
    │                                          └─────────────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
```

## Key Architectural Principles

1. **Domain Isolation**: Each domain is self-contained with its own entities, components, and adapters
2. **Single Responsibility**: Each component or adapter has a single, well-defined responsibility
3. **Cross-Domain Operations**: Handled explicitly in the sync domain
4. **API Separation**: REST and MCP adapters are separate from domain logic
5. **Type Safety**: Python enums for domain values, comprehensive type checking
6. **Real Database Testing**: Integration tests with Docker PostgreSQL for production parity
7. **Test-Driven Development**: Unit and integration tests guide implementation
8. **Transactional Events**: Domain events stored in outbox table within same transaction as main data
9. **Search-First Design**: All entities indexed in MeiliSearch for fast, typo-tolerant search

## Quick Start

For implementation details and getting started:

1. **Start with [Domain Architecture](./architecture/domain-architecture.md)** to understand the core design patterns
2. **Review [Database Design](./architecture/database-design.md)** for data modeling and schema
3. **Check [Technology Stack](./architecture/technology-stack.md)** for implementation technologies
4. **Study [Testing Strategy](./architecture/testing-strategy.md)** for test-driven development patterns
5. **Review [API Design](./architecture/api-design.md)** for REST and MCP implementation patterns
6. **Check [Frontend Design](./architecture/frontend-design.md)** for component and UI patterns
7. **Follow [Deployment Guide](./architecture/deployment-guide.md)** for setting up the environment
8. **Consider [Security & Performance](./architecture/security-performance.md)** for production readiness
9. **Explore [Future Roadmap](./architecture/future-roadmap.md)** for planned enhancements

---

*This architecture supports agile, iterative development with clear separation of concerns and extensibility for future enhancements.*
