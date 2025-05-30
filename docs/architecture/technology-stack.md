# Technology Stack - Personal CRM & Journal System

This document outlines the technology choices, implementation details, and development tools for the Personal CRM & Journal System.

## Backend Technology Stack

### Runtime and Language
- **Runtime**: Node.js 24 (current LTS)
- **Language**: TypeScript 5+ with strict mode
- **Module System**: ES modules with proper import/export
- **Build Tool**: tsc or esbuild for production builds

### Web Framework and API
- **Web Framework**: Fastify (chosen for better TypeScript support and performance)
- **API Standard**: JSON API specification compliance
- **API Documentation**: @fastify/swagger for automatic OpenAPI generation
- **Request Validation**: Zod for runtime validation and schema generation
- **Middleware**: CORS, helmet, compression, rate limiting via Fastify plugins

### Database and ORM
- **Database**: SQLite with WAL mode for better concurrency
- **ORM**: Drizzle ORM (chosen for lightweight, type-safe, SQL-like syntax that works well with AI assistants)
- **Migrations**: Drizzle Kit for automatic migration generation and management
- **Connection Pooling**: better-sqlite3 with pooling
- **Schema Management**: TypeScript-first schema definition with automatic type inference

### Database Migrations (Drizzle Kit)
- **Migration Tool**: Drizzle Kit - official migration tool for Drizzle ORM
- **Generation**: Automatic migration generation from schema changes
- **Versioning**: Git-tracked migration files with timestamps
- **Commands**:
  - `drizzle-kit generate` - Generate migrations from schema changes
  - `drizzle-kit migrate` - Apply pending migrations
  - `drizzle-kit studio` - Visual database browser and editor
- **AI Benefits**:
  - Clear, readable SQL migration files
  - TypeScript schema definitions that AI assistants understand well
  - Automatic type safety between schema and queries

### Authentication and Security
- **Authentication**: NextAuth.js with Google OAuth 2.0 (chosen for Next.js integration and AI assistant familiarity)
- **Session Management**: NextAuth.js built-in session management with JWT
- **Password Hashing**: NextAuth.js handles authentication, bcrypt for any additional local passwords
- **API Security**: Rate limiting, input sanitization, CORS configuration via Fastify plugins

### Logging and Observability
- **Logging**: Winston with structured logging (JSON format)
- **Observability**: OpenTelemetry for tracing, metrics, and correlation
- **Monitoring**: Custom metrics for business operations
- **Health Checks**: Built-in health endpoints for monitoring

### Testing Framework
- **Unit Testing**: Jest with TypeScript support
- **Test Coverage**: 80%+ coverage requirement
- **Mocking**: Jest mocks for external dependencies
- **Test Database**: In-memory SQLite for fast test execution

## Frontend Technology Stack

### Framework and Language
- **Framework**: Next.js 14+ with React 18+ (chosen for full-stack capabilities and AI assistant familiarity)
- **Language**: TypeScript with strict mode
- **Build Tool**: Next.js built-in (Turbopack/Webpack)
- **Module Bundler**: Built-in with Next.js

### Styling and UI
- **Styling**: Tailwind CSS with utility-first approach
- **UI Components**: shadcn/ui (chosen for excellent AI assistant support and Radix UI foundation)
- **Icons**: Lucide React (included with shadcn/ui)
- **Responsive Design**: Mobile-first approach with Tailwind breakpoints

### State Management
- **State Management**: Zustand (chosen for simplicity and AI assistant familiarity)
- **Server State**: TanStack Query (React Query) for API state caching
- **Form State**: React Hook Form with Zod validation
- **Local Storage**: Zustand persist middleware

### Localisation and Formatting
- **Localisation**: Australian English (en-AU) with react-intl
- **Date/Time**: date-fns with en-AU locale for Australian formatting
- **Number Formatting**: Intl.NumberFormat with Australian locale
- **Currency**: Australian Dollar (AUD) formatting

### Development Tools
- **Hot Reload**: Built-in with Next.js
- **Type Checking**: TypeScript compiler with strict mode
- **Linting**: ESLint with TypeScript and React rules
- **Formatting**: Prettier with consistent configuration

## External APIs and Libraries

### Google Integration
- **Google APIs**: Official `googleapis` npm package with TypeScript support
- **Google Calendar API**: v3 via googleapis with proper scoping
- **Google Contacts API**: People API v1 via googleapis
- **Authentication**: Google OAuth 2.0 with PKCE flow
- **Rate Limiting**: Built-in rate limiting and exponential backoff

### Immich Integration
- **Immich API**: Using `@immich/sdk` and docs at https://immich.app/docs/api
- **Authentication**: API key or session-based authentication

### MCP Protocol
- **MCP Implementation**: `@modelcontextprotocol/sdk` - Official MCP SDK
- **Transport**: Streamable HTTP Transport for web-compatible integration
- **Server Framework**: MCP Server with HTTP-based client connections
- **Tool Registration**: Dynamic tool registration and discovery via SDK
- **Resource Management**: Efficient resource handling and caching
- **Authentication**: OAuth based authentication

### HTTP and Networking
- **HTTP Client**: Axios with interceptors for observability
- **Request/Response**: Automatic retry with exponential backoff
- **Timeout Handling**: Configurable timeouts for different operations
- **Error Handling**: Structured error responses and logging

## Testing Strategy

### Multi-Layer Testing Approach

#### Unit Tests (Jest)
- **Coverage**: 80%+ code coverage requirement
- **Scope**: Individual functions, classes, and components
- **Mocking**: External dependencies and database operations
- **Performance**: Fast execution with parallel test runs
- **Configuration**: Jest with TypeScript and ES modules support

#### Component Tests (Storybook)
- **Scope**: Isolated React component testing
- **Documentation**: Living documentation of component APIs
- **Visual Testing**: Visual regression testing with Chromatic
- **Accessibility**: Built-in accessibility testing with axe-core
- **Interaction Testing**: User interaction testing within Storybook

#### Integration Tests (Jest)
- **Scope**: API endpoints and service integration
- **Database**: Test database with realistic data
- **External APIs**: Mocked external services with realistic responses
- **Authentication**: Test authentication flows and authorization
- **Error Scenarios**: Test error handling and edge cases

#### End-to-End Tests (Playwright)
- **Scope**: Complete user workflows and business scenarios
- **Browsers**: Multi-browser testing (Chrome, Firefox, Safari)
- **Mobile**: Mobile device testing and responsive design
- **Performance**: Page load times and interaction performance
- **Accessibility**: Full accessibility testing with axe-core

#### Visual Testing
- **Tool**: Storybook with Chromatic for visual regression
- **Scope**: UI component visual consistency
- **Responsive**: Testing across different screen sizes
- **Themes**: Testing light/dark themes if applicable
- **Cross-browser**: Visual consistency across browsers

#### Performance Testing
- **Tool**: Lighthouse CI for automated performance testing
- **Metrics**: Core Web Vitals and custom performance metrics
- **API Performance**: Response time testing for API endpoints
- **Database Performance**: Query performance and optimization testing
- **Load Testing**: Basic load testing for critical endpoints

## Development Tools and Quality

### Code Quality
- **Linting**: ESLint with strict rules and architectural linting
- **Formatting**: Prettier with consistent configuration
- **Type Checking**: TypeScript strict mode with no implicit any
- **Pre-commit Hooks**: Husky with lint-staged for quality gates
- **Dependency Injection**: tsyringe (chosen for decorator patterns and AI assistant compatibility)

### Build and Development
- **Package Manager**: pnpm (chosen for efficiency and monorepo support)
- **Monorepo**: pnpm workspaces for frontend/backend organization
- **Build Tools**:
  - Frontend: Next.js built-in build system (Turbopack/Webpack)
  - Backend: esbuild for fast TypeScript compilation
- **Build Scripts**: Standardized pnpm scripts for common tasks
- **Environment Management**: dotenv for environment configuration
- **Hot Reload**: Fast development with hot module replacement

### Monorepo Structure (AI-Optimized)
```
personal-management-system/
├── apps/
│   ├── frontend/          # Next.js application
│   └── backend/           # Fastify API server
├── packages/
│   ├── shared/            # Shared TypeScript types and utilities
│   ├── database/          # Drizzle schema, migrations, and seed data
│   └── ui/                # Shared UI components (if needed)
├── docker/                # Multi-container Docker configurations
├── docs/                  # Architecture and development documentation
└── tools/                 # Development tools and scripts
```

### Documentation
- **API Documentation**: Automatic OpenAPI/Swagger generation
- **Code Documentation**: TSDoc comments for complex functions
- **Architecture Documentation**: Markdown files with diagrams
- **Component Documentation**: Storybook for component library

### Version Control and CI/CD
- **Version Control**: Git with conventional commits
- **Branching**: GitFlow or GitHub Flow for feature development
- **CI/CD**: GitHub Actions or similar for automated testing and deployment
- **Code Review**: Pull request reviews with automated checks

## Deployment Strategy

### Container Architecture
- **Strategy**: Multi-container deployment (chosen for better separation of concerns)
- **Frontend Container**: Next.js application with nginx for static serving
- **Backend Container**: Fastify API server
- **Database**: SQLite with volume mounting for persistence
- **Reverse Proxy**: nginx for routing and SSL termination
- **Orchestration**: Docker Compose for development, production-ready orchestration

### Container Benefits for AI Development
- **Isolation**: Clear separation between frontend and backend for AI assistants
- **Scalability**: Independent scaling of frontend and backend services
- **Development**: Consistent environments across development and production
- **Debugging**: Easier to isolate and debug individual services

## Configuration Management

### Environment Configuration
- **Development**: Local development with hot reload
- **Testing**: Isolated test environment with mocked services
- **Staging**: Production-like environment for final testing
- **Production**: Optimized production configuration

### Feature Flags
- **Implementation**: Simple feature flag system for gradual rollouts
- **Configuration**: Environment-based feature flag configuration
- **Testing**: Feature flag testing in different environments

### Secrets Management
- **Development**: .env files with example templates
- **Production**: Environment variables or secrets management system
- **API Keys**: Secure storage and rotation of API keys
- **Database**: Secure database connection string management

## Performance Optimization

### Frontend Performance
- **Code Splitting**: Dynamic imports for route-based code splitting
- **Bundle Optimization**: Tree shaking and dead code elimination
- **Image Optimization**: Next.js Image component or similar optimization
- **Caching**: Browser caching with proper cache headers

### Backend Performance
- **Database Optimization**: Query optimization and proper indexing
- **Caching**: In-memory caching for frequently accessed data
- **Connection Pooling**: Database connection pooling
- **Compression**: Response compression for API endpoints

### Monitoring and Metrics
- **Application Metrics**: Custom business metrics and performance indicators
- **Error Tracking**: Structured error logging and alerting
- **Performance Monitoring**: Response time and throughput monitoring
- **Resource Usage**: Memory and CPU usage monitoring

## Final Technology Stack Summary (AI-Optimized)

### Core Technology Decisions
| Component | Choice | AI Optimization Reason |
|-----------|--------|------------------------|
| **Package Manager** | pnpm | Monorepo support, efficiency, AI assistant familiarity |
| **Backend Framework** | Fastify | Better TypeScript support, cleaner patterns |
| **Frontend Framework** | Next.js 14+ | Extensive AI training data, full-stack capabilities |
| **UI Components** | shadcn/ui + Tailwind | Excellent AI assistant support, component patterns |
| **Database** | SQLite + Drizzle ORM | Explicit SQL syntax, type-safe, AI-friendly |
| **Migrations** | Drizzle Kit | Automatic generation, clear SQL files |
| **State Management** | Zustand | Simple patterns, predictable state flow |
| **Authentication** | NextAuth.js | Standard Next.js patterns, Google OAuth |
| **Dependency Injection** | tsyringe | Clear decorator patterns, TypeScript support |
| **API Documentation** | @fastify/swagger | Native Fastify integration |
| **Testing** | Jest + Storybook + Playwright | Well-established patterns |
| **Project Structure** | Monorepo (pnpm workspaces) | Full context for AI assistants |
| **Deployment** | Multi-container Docker | Clear separation of concerns |

### Key AI Development Benefits
1. **Explicit Patterns**: All choices favor explicit over implicit behavior
2. **TypeScript First**: Strong typing throughout the entire stack
3. **Standard Conventions**: Using well-established patterns AI assistants know
4. **Clear Separation**: Monorepo with clear domain boundaries
5. **Minimal Magic**: Reduced abstraction layers for better AI understanding

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Domain Architecture](./domain-architecture.md) - How technologies integrate with domain design
- [Database Design](./database-design.md) - Database technology implementation details
- [Deployment Guide](./deployment-guide.md) - Production deployment of technology stack
- [Security & Performance](./security-performance.md) - Security and performance considerations
