# Frontend Design - Personal CRM & Journal System

This document provides comprehensive frontend design patterns and component guidelines using shadcn/ui.

## Frontend Component Guidelines

### shadcn/ui Component Structure

- Use shadcn/ui components for consistent design system and AI assistant support
- Import components from `@/components/ui/` path with clear structure
- Use Lucide React icons for consistent iconography across the application
- Implement proper TypeScript interfaces for all component props
- Include accessibility attributes (`sr-only`, `aria-label`) for screen readers
- Use Tailwind CSS classes for styling with semantic color tokens
- Implement responsive design with mobile-first approach using Tailwind breakpoints

### Form Validation Guidelines

- Use React Hook Form with Zod for validation
- Import `zodResolver` for schema integration
- Define Zod schemas with clear error messages
- Use `FormField` components for consistent form structure
- Include `FormLabel`, `FormControl`, and `FormMessage`
- Add `FormDescription` for helpful field guidance
- Use Australian English terminology ("Organisation" not "Company")
- Provide realistic Australian placeholders (0400 000 000)

### Responsive Layout Guidelines

- Use CSS Grid with responsive breakpoints
- Start with single column on mobile (`grid-cols-1`)
- Scale up for larger screens (`sm:grid-cols-2`, `lg:grid-cols-3`)
- Adjust gaps proportionally with screen size
- Use consistent spacing patterns across components

### Tailwind Configuration Guidelines

- Enable class-based dark mode (`darkMode: ['class']`)
- Include all relevant file paths in content array
- Extend theme with CSS custom properties for shadcn/ui
- Add Australian-themed color palette when appropriate
- Include `tailwindcss-animate` plugin for animations

### Accessibility Guidelines

- Include `aria-label` attributes for screen readers
- Use `sr-only` class for screen reader only content
- Implement proper focus management with visible focus rings
- Ensure keyboard navigation works for all interactive elements
- Use semantic HTML elements and ARIA roles
- Test with screen readers and keyboard-only navigation

### Loading State Guidelines

- Use shadcn/ui `Skeleton` component for loading states
- Match skeleton dimensions to actual content layout
- Provide skeletons for all major content areas
- Use consistent spacing and proportions
- Implement smooth transitions between loading and loaded states

## Component Architecture

### Component Organization

- Organize components by feature/domain
- Use barrel exports for clean imports
- Separate UI components from business logic
- Create reusable compound components
- Follow single responsibility principle

### State Management

- Use React hooks for local component state management
- Implement custom hooks for shared logic and reusable patterns
- Use Zustand for global state management with simple, AI-friendly patterns
- Use TanStack Query for server state management and API caching
- Use React Hook Form with Zod validation for form state
- Keep state as close to usage as possible for maintainability

### TypeScript Integration

- Define interfaces for all component props
- Use generic types for reusable components
- Implement proper type guards for data validation
- Use discriminated unions for variant props
- Ensure type safety across component boundaries

## Design System

### Color Palette

- Use semantic color tokens from shadcn/ui
- Implement proper dark mode support
- Use CSS custom properties for theming
- Maintain consistent color usage across components
- Test color contrast for accessibility compliance

### Typography

- Use consistent font scales and weights
- Implement proper heading hierarchy
- Use semantic text classes for different contexts
- Ensure readable line heights and spacing
- Support responsive typography scaling

### Spacing and Layout

- Use consistent spacing scale (4px, 8px, 16px, etc.)
- Implement proper component spacing
- Use flexbox and grid for layout patterns
- Maintain consistent component proportions
- Support responsive layout adjustments

## Performance Optimization

### Code Splitting

- Implement route-based code splitting
- Use dynamic imports for heavy components
- Lazy load non-critical components
- Optimize bundle sizes with tree shaking
- Monitor bundle analysis regularly

### Image Optimization

- Use Next.js Image component for optimization
- Implement proper image lazy loading
- Use appropriate image formats (WebP, AVIF)
- Provide responsive image sizes
- Optimize images for different screen densities

### Rendering Optimization

- Use React.memo for expensive components
- Implement proper key props for lists
- Avoid unnecessary re-renders
- Use useMemo and useCallback appropriately
- Profile component performance regularly

## Testing Patterns

### Component Testing

- Test component rendering with various props
- Verify user interactions and event handling
- Test accessibility features and keyboard navigation
- Mock external dependencies and API calls
- Use realistic test data and scenarios

### Integration Testing

- Test component integration with forms
- Verify data flow between components
- Test error handling and edge cases
- Ensure proper loading and error states
- Test responsive behavior across breakpoints

## Australian Localization

### Date and Time Formatting

- Use DD/MM/YYYY date format
- Implement proper timezone handling (AEST/AEDT)
- Use Australian English date terminology

### Language and Terminology

- Use Australian English spelling and terminology
- Implement proper currency formatting (AUD)
- Use Australian business terminology
- Support metric units and measurements
- Provide Australian-specific help text and examples

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and frontend principles
- [AI Guidelines](../ai-guidelines.md) - Frontend development standards and guidelines
- [Technology Stack](./technology-stack.md) - Frontend technology choices and frameworks
- [Domain Architecture](./domain-architecture.md) - Domain patterns for frontend integration
- [API Design](./api-design.md) - API integration patterns for frontend
- [Testing Strategy](./testing-strategy.md) - Component testing patterns and accessibility testing
- [Deployment Guide](./deployment-guide.md) - Frontend deployment configuration and Docker setup
