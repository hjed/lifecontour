# Personal Management System - Frontend

Next.js TypeScript frontend for the Personal CRM & Journal System with shadcn/ui components, Tailwind CSS, and Australian English localization.

## Quick Start

### Prerequisites

- Node.js 22+
- pnpm 11+

### Development Setup

1. **Install dependencies:**

   ```bash
   pnpm install
   ```

2. **Set up environment:**

   ```bash
   cp .env.example .env.local
   # Edit .env.local with your configuration
   ```

3. **Start development server:**

   ```bash
   pnpm dev
   ```

4. **Open in browser:**
   http://localhost:3000

### Building

```bash
# Build for production
pnpm build

# Start production server
pnpm start
```

### Testing

```bash
# Run unit tests
pnpm test

# Run tests in watch mode
pnpm test:watch

# Run tests with coverage
pnpm test:coverage

# Run end-to-end tests
pnpm test:e2e

# Run e2e tests with UI
pnpm test:e2e:ui
```

### Code Quality

```bash
# Linting
pnpm lint
pnpm lint:fix

# Type checking
pnpm type-check

# Formatting
pnpm format
pnpm format:check
```

## Features

- **shadcn/ui Components**: Modern, accessible UI components
- **Tailwind CSS**: Utility-first CSS framework with dark mode support
- **Australian English**: DD/MM/YYYY date formats and en-AU locale
- **TypeScript**: Full type safety throughout the application
- **Responsive Design**: Mobile-first approach with responsive layouts
- **Testing**: Jest, React Testing Library, and Playwright for comprehensive testing

## Architecture

The frontend follows modern React patterns with:

- **App Router**: Next.js 14 app directory structure
- **Component Library**: shadcn/ui for consistent, accessible components
- **Type Safety**: TypeScript interfaces for all API interactions
- **State Management**: React hooks and context for local state
- **API Integration**: Typed API client for backend communication

See [Architecture Documentation](../docs/architecture.md) for detailed information.
