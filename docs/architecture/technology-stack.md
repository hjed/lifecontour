# Technology Stack - Personal CRM & Journal System

This document outlines the technology choices, implementation details, and development tools for the Personal CRM & Journal System.

## Backend Technology Stack

### Runtime and Language
- **Runtime**: Node.js 24 (current LTS)
- **Language**: TypeScript 5+ with strict mode
- **Module System**: ES modules with proper import/export
- **Build Tool**: tsc or esbuild for production builds

### Web Framework and API
- **Web Framework**: Express.js or Fastify
- **API Standard**: JSON API specification compliance
- **API Documentation**: tsoa or @nestjs/swagger for automatic OpenAPI generation
- **Request Validation**: Zod for runtime validation and schema generation
- **Middleware**: CORS, helmet, compression, rate limiting

### Database and ORM
- **Database**: SQLite with WAL mode for better concurrency
- **ORM Options**:
  - **Drizzle ORM**: Lightweight, type-safe, SQL-like syntax
  - **Prisma**: Feature-rich with excellent TypeScript support
- **Migrations**: Version-controlled schema migrations
- **Connection Pooling**: better-sqlite3 or sqlite3 with pooling

### Authentication and Security
- **Authentication**: OAuth 2.0 (Google), JWT for sessions
- **Session Management**: JWT with refresh token rotation
- **Password Hashing**: bcrypt or argon2 for any local passwords
- **API Security**: Rate limiting, input sanitization, CORS configuration

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
- **Framework**: React 18+ with Next.js or Vite
- **Language**: TypeScript with strict mode
- **Build Tool**: Vite (fast) or Next.js (full-stack)
- **Module Bundler**: Built-in with chosen framework

### Styling and UI
- **Styling**: Tailwind CSS with utility-first approach
- **UI Components**: Radix UI or Headless UI (Tailwind compatible)
- **Icons**: Lucide React or Heroicons
- **Responsive Design**: Mobile-first approach with Tailwind breakpoints

### State Management
- **State Management**: Zustand (lightweight) or Redux Toolkit (complex state)
- **Server State**: TanStack Query (React Query) for API state
- **Form State**: React Hook Form with Zod validation
- **Local Storage**: Zustand persist middleware

### Localisation and Formatting
- **Localisation**: Australian English (en-AU) with react-intl
- **Date/Time**: date-fns with en-AU locale for Australian formatting
- **Number Formatting**: Intl.NumberFormat with Australian locale
- **Currency**: Australian Dollar (AUD) formatting

### Development Tools
- **Hot Reload**: Built-in with Vite or Next.js
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

### Build and Development
- **Package Manager**: npm or pnpm for dependency management
- **Build Scripts**: Standardized npm scripts for common tasks
- **Environment Management**: dotenv for environment configuration
- **Hot Reload**: Fast development with hot module replacement

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

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Domain Architecture](./domain-architecture.md) - How technologies integrate with domain design
- [Database Design](./database-design.md) - Database technology implementation details
- [Deployment Guide](./deployment-guide.md) - Production deployment of technology stack
- [Security & Performance](./security-performance.md) - Security and performance considerations
