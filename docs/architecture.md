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
- **Clear Language Separation**: Python backend, TypeScript frontend for AI clarity
- **Agile Development**: Feature-complete iterations delivering incremental value
- **Proxy-Ready**: Support deployment behind nginx reverse proxy
- **AI-Optimized**: Explicit patterns and readable code over performance optimization

## Architecture Documentation

This document provides a high-level overview of the system architecture. For detailed information, refer to the following documents:

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
- Testing strategy and quality assurance
- External APIs and library integrations
- Development tools and configuration

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
    │  │ │+ Tags   │ │ │ │+ Albums │ │ │ │+ Albums │ │ ││+ Albums│ │  │
    │  │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │└────────┘ │  │
    │  │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │ │┌────────┐ │  │
    │  │ │Adapters │ │ │ │Adapters │ │ │ │Adapters │ │ ││Adapters│ │  │
    │  │ │(SQL,etc)│ │ │ │(SQL,etc)│ │ │ │(SQL,etc)│ │ ││(SQL,etc)││ │
    │  │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │└────────┘ │  │
    │  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘  │
    └─────────────────────────────────────────────────────────────────┘
                                    │
    ┌─────────────────────────────────────────────────────────────────┐
    │                  Integration Sub-Domains                        │
    │  ┌─────────────────┐              ┌─────────────────────────────┐ │
    │  │     Google      │              │          Immich             │ │
    │  │   Integration   │              │       Integration           │ │
    │  │                 │              │                             │ │
    │  │ ┌─────────────┐ │              │ ┌─────────────────────────┐ │ │
    │  │ │Sync Logic   │ │              │ │Album & Person Logic     │ │ │
    │  │ │Tag Sync     │ │              │ │Name-Based Matching      │ │ │
    │  │ │Contact Sync │ │              │ │Auto Contact Linking     │ │ │
    │  │ │Calendar Sync│ │              │ │Journal/Event Albums     │ │ │
    │  │ └─────────────┘ │              │ └─────────────────────────┘ │ │
    │  │ ┌─────────────┐ │              │ ┌─────────────────────────┐ │ │
    │  │ │Adapters     │ │              │ │Adapters                 │ │ │
    │  │ │Google APIs  │ │              │ │Immich Client            │ │ │
    │  │ │Sync State   │ │              │ │Sync State               │ │ │
    │  │ └─────────────┘ │              │ └─────────────────────────┘ │ │
    │  └─────────────────┘              └─────────────────────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
```

## Key Architectural Principles

1. **Domain Isolation**: Each domain is self-contained with its own entities, components, and adapters
2. **Single Responsibility**: Each component or adapter has a single, well-defined responsibility
3. **Cross-Domain Operations**: Handled explicitly in the sync domain
4. **API Separation**: REST and MCP adapters are separate from domain logic

## Quick Start

For implementation details and getting started:

1. **Start with [Domain Architecture](./architecture/domain-architecture.md)** to understand the core design patterns
2. **Review [Database Design](./architecture/database-design.md)** for data modeling and schema
3. **Check [Technology Stack](./architecture/technology-stack.md)** for implementation technologies
4. **Follow [Deployment Guide](./architecture/deployment-guide.md)** for setting up the environment
5. **Consider [Security & Performance](./architecture/security-performance.md)** for production readiness
6. **Explore [Future Roadmap](./architecture/future-roadmap.md)** for planned enhancements

---

*This architecture supports agile, iterative development with clear separation of concerns and extensibility for future enhancements.*
