# Component Patterns - shadcn/ui Guidelines

## Frontend Component Guidelines

### shadcn/ui Component Structure
- Use shadcn/ui components for consistent design system
- Import components from `@/components/ui/` path
- Use Lucide React icons for consistent iconography
- Implement proper TypeScript interfaces for props
- Include accessibility attributes (`sr-only`, `aria-label`)
- Use Tailwind CSS classes for styling
- Implement responsive design with mobile-first approach

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
