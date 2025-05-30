# Personal Management System

A personal CRM & journal system with MCP protocol support, Google integration,
and Immich photo management.

## 🚀 Features

- **Personal CRM**: Manage contacts with tags and Google sync
- **Journal**: Track thoughts, experiences, and mood with photo integration
- **Calendar**: Sync with Google Calendar and link events to photos
- **MCP Protocol**: Model Context Protocol support for AI assistants
- **Photo Integration**: Connect with Immich for photo management

## 🏗️ Architecture

This is a modern TypeScript monorepo built with:

- **Backend**: Fastify API with OpenTelemetry observability
- **Frontend**: Next.js 14 with shadcn/ui components
- **Database**: SQLite with Drizzle ORM
- **Deployment**: Multi-container Docker setup with nginx proxy
- **Development**: pnpm workspaces with comprehensive tooling

## 📋 Current Status: ITER1-001 - Project Foundation

This project follows an agile iterative approach. Currently implemented:

- ✅ Monorepo structure with pnpm workspaces
- ✅ TypeScript configuration with strict mode
- ✅ ESLint with architectural boundary rules
- ✅ Prettier formatting
- ✅ Pre-commit hooks with Husky
- ✅ Domain-driven folder structure
- ✅ Dependency injection with tsyringe
- ✅ OpenTelemetry auto-instrumentation
- ✅ Structured logging with Winston
- ✅ Fastify server with comprehensive middleware
- ✅ Next.js frontend with Tailwind CSS
- ✅ Testing setup (Jest, Storybook, Playwright)
- ✅ Multi-container Docker deployment
- ✅ Australian locale support

## 🛠️ Development Setup

### Prerequisites

- Node.js 24+
- pnpm 9.12+
- Docker (for deployment)

### Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd personal-management-system
```

2. Install dependencies:

```bash
pnpm install
```

3. Set up environment variables:

```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Start development servers:

```bash
# Start all services in development mode
pnpm dev

# Or start individual services
pnpm --filter backend dev
pnpm --filter frontend dev
```

### Available Scripts

```bash
# Development
pnpm dev              # Start all services in development
pnpm build            # Build all packages
pnpm test             # Run all tests
pnpm lint             # Lint all code
pnpm format           # Format all code

# Database
pnpm db:generate      # Generate database migrations
pnpm db:migrate       # Apply database migrations
pnpm db:studio        # Open database studio

# Testing
pnpm test:watch       # Run tests in watch mode
pnpm test:e2e         # Run end-to-end tests
pnpm storybook        # Start Storybook

# Docker
pnpm docker:build     # Build Docker images
pnpm docker:up        # Start Docker containers
pnpm docker:down      # Stop Docker containers
```

## 🐳 Docker Deployment

The system uses a multi-container architecture:

- **Frontend**: Next.js application
- **Backend**: Fastify API server
- **Database**: SQLite with volume persistence
- **Nginx**: Reverse proxy with SSL termination

```bash
# Build and start all containers
pnpm docker:up

# Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:3001
# API Documentation: http://localhost:3001/docs
```

## 📁 Project Structure

```
personal-management-system/
├── apps/
│   ├── frontend/          # Next.js application
│   └── backend/           # Fastify API server
├── packages/
│   ├── shared/            # Shared types and utilities
│   └── database/          # Drizzle schema and migrations
├── docker/                # Multi-container Docker setup
├── docs/                  # Architecture and development docs
└── tools/                 # Development tools and scripts
```

## 🧪 Testing

The project includes comprehensive testing setup:

- **Unit Tests**: Jest with TypeScript support
- **Component Tests**: React Testing Library
- **E2E Tests**: Playwright
- **Visual Tests**: Storybook
- **Coverage**: 80% threshold requirement

```bash
# Run all tests
pnpm test

# Run tests with coverage
pnpm test:coverage

# Run E2E tests
pnpm test:e2e

# Start Storybook
pnpm storybook
```

## 🔧 Code Quality

- **TypeScript**: Strict mode with comprehensive type checking
- **ESLint**: Architectural boundary rules and best practices
- **Prettier**: Consistent code formatting
- **Husky**: Pre-commit hooks for quality gates
- **lint-staged**: Staged file linting and formatting

## 📚 Documentation

- [Architecture Overview](docs/architecture.md)
- [Technology Stack](docs/architecture/technology-stack.md)
- [AI Guidelines](docs/ai-guidelines.md)
- [Tasks and Iterations](docs/tasks.md)

## 🗺️ Roadmap

### Next Iterations

- **ITER1-002**: Contacts Domain Core
- **ITER1-003**: Journal Domain Core
- **ITER1-004**: Calendar Domain Core
- **ITER1-005**: Google Integration
- **ITER1-006**: Immich Integration
- **ITER1-007**: MCP Protocol Support

## 🤝 Contributing

This is a personal project, but contributions are welcome! Please:

1. Follow the existing code style and patterns
2. Add tests for new functionality
3. Update documentation as needed
4. Use the established commit message format

## 📄 License

AGPLv3 License

## 🙋‍♂️ Support

For questions or issues, please check the documentation or create an issue in
the repository.
