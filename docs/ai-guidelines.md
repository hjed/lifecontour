# AI Development Guidelines - Personal CRM & Journal System

## Project Context

This document provides essential guidelines for AI assistants working on the
Personal CRM & Journal System. The system is a TypeScript/Node.js application
that integrates personal data from multiple sources with both MCP (Model Context
Protocol) and web interfaces.

Refer to the [architecture document](./architecture.md) for a high-level
overview of the system architecture and navigation.

Tasks can be found in the [tasks document](./tasks.md).

### Key Technologies

- **Backend**: TypeScript/Node.js 24, SQLite database
- **Frontend**: React with shadcn/ui components, Tailwind CSS
- **APIs**: JSON API standard for REST endpoints, MCP for AI integration
- **Testing**: Jest (unit), Storybook (components), Playwright (e2e)
- **Integrations**: Google Calendar/Contacts, Immich photos
- **Deployment**: Docker with nginx proxy support
- **Localization**: Australian English

### Core Principles

1. **Type Safety**: Leverage TypeScript's strict type system
2. **Domain-Driven Architecture**: Core domains with separate integration
   sub-domains
3. **Agile Development**: Feature-complete iterations delivering incremental
   value. Future proof without over-engineering.
4. **Integration Isolation**: External integrations in separate sub-domains
5. **AI-Friendly**: Design APIs and data structures for easy AI consumption
6. **Clear Boundaries**: Clear separation between each domain and between core
   and integration domains.

## Agile Development Approach

### Feature-Complete Iterations

- Each iteration delivers working, testable functionality end-to-end
- Build domain logic → adapters → application services → API endpoints → basic
  UI
- Deploy and test after each iteration
- Integration sub-domains developed separately from core domains
- Architecture can evolve - check technology choices with user before acting

### Development Sequence

1. **Documentation** - document any planned changes, confirm design decisions
   for itteration.
2. **Domain logic** - entities, value objects, business rules and their unit
   tests
3. **Adapters** - database repositories, external API clients and their tests,
   including integration tests
4. **API endpoints** - REST controllers with JSON API compliance
5. **Basic UI** - functional interface using shadcn/ui
6. **Tests** - unit, integration, and end-to-end all working. Coverage complete
7. **Deploy and validate** - ensure feature works in real environment

## Testing Strategy

### Three-Layer Testing Approach

1. **Unit Tests (Jest)** - Domain entities, value objects, and business logic
2. **Component Tests (Storybook)** - React components with shadcn/ui integration
3. **End-to-End Tests (Playwright)** - Full user workflows and Australian
   localization

### Testing Requirements

- **Coverage**: Minimum 80% code coverage for all domains
- **Australian Localization**: Test date formats (DD/MM/YYYY)
- **Accessibility**: ARIA attributes, keyboard navigation, screen reader support
- **shadcn/ui Integration**: Component interactions, theming, responsive design

_See [Testing Patterns](./examples/testing-patterns.md) for detailed examples
and implementation guides._

## Frontend Development Standards

### shadcn/ui Component Guidelines

- Use shadcn/ui components with proper TypeScript interfaces
- Implement proper accessibility with ARIA attributes and screen reader support
- Follow responsive design patterns with mobile-first approach
- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`

### Key Patterns

- **Cards**: Use `Card`, `CardHeader`, `CardContent` for consistent layouts
- **Forms**: Integrate with react-hook-form and Zod validation
- **Dropdowns**: Include keyboard navigation and proper ARIA attributes
- **Badges**: Use for tags with custom colors via style prop

_See [Component Patterns](./examples/component-patterns.md) for detailed
shadcn/ui implementation examples._

### Tailwind CSS Guidelines

- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`
- Follow mobile-first responsive design with `sm:`, `lg:`, `xl:` prefixes
- Leverage shadcn/ui's CSS custom properties for theming

### Australian English Localisation

#### Key Requirements

- **Date Format**: DD/MM/YYYY (not MM/DD/YYYY) for user display. Use ISO format
  for machine-to-machine communication.
- **Currency**: AUD formatting with Intl.NumberFormat('en-AU')
- **Locale**: Use 'en-AU' for react-intl and date-fns

## Development Standards

### TypeScript Configuration

- Always define interfaces for API objects, database entities, configuration,
  and MCP tools
- Use exact optional property types for better type safety

### Code Organization

#### Folder Structure

```
src/
├── api/                          # API Adapters (REST & MCP)
├── contacts/                     # Contacts Core Domain
│   ├── domain/                   # Entities, value objects, services
│   ├── adapters/                 # SQL repositories, event publishers
│   └── application/              # Use cases, application components
├── calendar/                     # Calendar Core Domain
├── journal/                      # Journal Core Domain
├── photos/                       # Photos Core Domain
├── google-integration/           # Google Integration Sub-Domain
├── immich-integration/           # Immich Integration Sub-Domain
└── shared/                       # Database, events, config, proxy utils
```

#### Naming Conventions

- **Files**: kebab-case (`contact-service.ts`)
- **Classes**: PascalCase (`ContactService`)
- **Functions/Variables**: camelCase (`getUserContacts`)
- **Constants**: UPPER_SNAKE_CASE (`MAX_RETRY_ATTEMPTS`)

### Domain-Driven Architecture Patterns

#### Key Architectural Rules

1. **Core domains** (contacts, calendar, journal, photos) contain only business
   logic
2. **Integration sub-domains** (google-integration, immich-integration) handle
   external systems
3. **Adapters** within domains can only access their own domain's business logic
4. **Cross-domain communication** happens through application services and
   events
5. **Integration sub-domains** can access multiple core domains via their
   application services

#### Essential Patterns

- **Entities**: Rich domain objects with identity and business logic
- **Value Objects**: Immutable objects representing domain concepts (Email,
  PhoneNumber)
- **Application Components**: Orchestrate use cases and coordinate between
  domains
- **Adapters**: Implement external dependencies (SQL repositories, API clients)

_See [Domain Architecture](./examples/domain-architecture.md) for detailed
implementation patterns and examples._

## Essential Development Practices

### Error Handling

- Create custom error classes with meaningful names and context
- Always handle errors explicitly with try/catch blocks
- Use structured logging for error context
- Return result objects: `{ success: boolean, data?: T, error?: string }`

### Database Operations

- Use transactions for multi-table operations
- Always use prepared statements to prevent SQL injection
- Implement proper connection pooling and lifecycle management

### API Design

- **JSON API Compliance**: Follow JSON API specification for REST endpoints
- **Input Validation**: Use Zod schemas for all request validation
- **Error Responses**: Return structured JSON API error format
- **Pagination**: Implement cursor-based pagination for large datasets

### MCP Implementation

- Structure MCP tools with consistent interfaces - following the specification
- Make responses AI-friendly with context and summaries, not raw database data
- Provide search context and metadata in responses

### Security & Performance

- **Logging**: Use structured logging with appropriate levels (error, warn,
  info, debug)
- **Security**: Never log sensitive data, validate/sanitize inputs, use
  environment variables for secrets
- **Performance**: Index frequently queried columns, implement pagination, use
  connection pooling
- **Testing**: 80% coverage threshold, mock external integrations, test error
  scenarios

## Reference Documentation

For detailed implementation examples and patterns, see:

- **[Testing Patterns](./examples/testing-patterns.md)** - Jest, Storybook, and
  Playwright examples
- **[Component Patterns](./examples/component-patterns.md)** - shadcn/ui
  implementation guides
- **[Domain Architecture](./examples/domain-architecture.md)** - DDD patterns
  and code examples
- **[API Patterns](./examples/api-patterns.md)** - REST and MCP implementation
  guides
- **[Configuration Examples](./examples/configuration/)** - Docker, environment,
  and deployment configs

## Key Reminders

1. **Check with user** before making technology choices or architectural changes
2. **Start simple** - implement core functionality before optimizations
3. **Test thoroughly** - write tests as you build, not after. Ideally before
   implementing.
4. **Document decisions** - update architecture docs when patterns evolve
