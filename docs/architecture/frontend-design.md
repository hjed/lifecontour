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

Tailwind v4 is configured **entirely from CSS**, in `frontend/src/app/globals.css`.
There is no `tailwind.config.js`/`.cjs` — v4 only loads one via an explicit
`@config` directive, and we deliberately do not use it (see #1186).

- **Theme tokens**: define them in the `@theme inline` block. Token values are
  self-contained colours (oklch) consumed as `var(--token)` — **never**
  `hsl(var(--token))`, which is a v3 contract that compiles to an invalid colour
  (see #1178). Light values live in `:root`, dark overrides in `.dark`.
- **Plugins**: register with `@plugin '<pkg>';` (e.g. `@tailwindcss/typography`).
  A v3 `plugins: [...]` array does nothing.
- **Animations**: `animate-in` / `animate-out` and friends come from
  `@import 'tw-animate-css';`. The v3-only `tailwindcss-animate` plugin is not
  compatible with v4.
- **Source detection**: automatic. There is no `content` array to maintain.
- Prefer the semantic token classes (`bg-background`, `text-muted-foreground`,
  `border-border`) over raw colours so light and dark both work.

A missing `@import` or `@plugin` does **not** fail the build — the affected
utilities just emit no CSS and the UI renders silently unstyled. Utilities the UI
depends on are therefore asserted in
`frontend/src/app/__tests__/globals-css.test.ts`; extend it when adding a plugin.

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

### Invalidating After a Mutation

Mutation handlers must refresh the cache through
`invalidateAfterMutation(queryClient, ...filters)`
(`frontend/src/lib/api/invalidate-after-mutation.ts`) rather than calling
`queryClient.invalidateQueries` directly.

- **Why:** `invalidateQueries` only cancels an in-flight request when the query
  *already has data*. A list loading for the first time — a fresh mount, or a new
  query key from a filter change — keeps the request that started before the
  mutation; when it settles, React Query caches its pre-mutation rows, clears
  `isInvalidated` and stamps a fresh `dataUpdatedAt`, so the app-wide five-minute
  `staleTime` suppresses any refetch and the user keeps seeing data they just
  changed ([#1203](https://github.com/hjed/personal-management-system/issues/1203)).
  The helper cancels first, which has no such guard.
- **Pass every key set in one call** — `invalidateAfterMutation(queryClient, { queryKey: a }, { queryKey: b })`
  — not one call per key. All the key sets must be cancelled before any of them
  is invalidated, or the later ones stay exposed to the same race.
- Optimistic handlers keep their existing `cancelQueries` in `onMutate`; their
  `onSuccess`/`onSettled` still invalidates through the helper.
- A filter asking for `refetchType: 'none'` cancels only the queries that
  already hold data. Cancelling a first-load query nothing is going to refetch
  would strand its observer on a spinner, so its request is allowed to land.
- Call it fire-and-forget (`void invalidateAfterMutation(...)`) as the old
  `invalidateQueries` calls were; `await` it only where the handler already
  awaited the refresh.

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

## Outdoor Logbook Overview Page

The Outdoor Logbook overview page (`src/app/journals/outdoor-logbook/page.tsx`)
is a dedicated route under the journals experience with its own sidebar entry
under Journals (not a calendar/list view-mode toggle). It is the shared shell
for outdoor logbook review and reporting: it hosts the incomplete outdoor
activities review, and the dashboard widgets (upcoming activities, checked-out
gear, recent totals, templates done) slot in alongside it (ITER16-003).

### Incomplete Outdoor Activities Review

- **Component**: `src/components/journals/IncompleteOutdoorActivitiesList.tsx`
  — a card listing each flagged journal with its title (linking to the journal
  detail), date range, type icon badges (reusing `JournalTypeBadges`), one
  reason badge per matched rule, and a dismiss/un-dismiss control.
- **API adapter**: `src/lib/api/incomplete-outdoor-activities.ts` — TanStack
  Query hooks over `GET /api/journals/incomplete-outdoor-activities` and the
  dismiss/undismiss action POSTs. Dismissing optimistically removes the entry
  from the default list and offers an Undo toast action.
- **Show dismissed**: a labelled switch refetches with
  `include_dismissed=true`; dismissed rows render muted with an Un-dismiss
  button, giving a durable un-dismiss affordance (dismissed entries are
  otherwise excluded from the review).
- **Accessibility**: semantic `ul`/`li` list, per-row `aria-label`s on the
  dismiss/un-dismiss buttons (including the journal title), a `Label`-linked
  switch, and semantic colour tokens throughout.

### Dashboard Widgets

- **API adapter**: `src/lib/api/outdoor-dashboard.ts` — a single TanStack
  Query hook (`useOutdoorDashboard`) over the singleton
  `GET /api/journals/outdoor-dashboard` resource. All dashboard widgets call
  the same hook and share one query key, so concurrent mounts dedupe into one
  fetch; the adapter types all four dashboard sections (upcoming activities,
  checked-out gear, activity totals, templates done).
- **Upcoming activities**: `src/components/journals/UpcomingActivitiesList.tsx`
  — a card listing the next 30 days of outdoor activities and planning events
  (soonest first, capped at 10 server-side), each with its title (linking to
  the journal), date range, and type icon badges. Planning entries show the
  Outdoor Planning badge; activity entries show their raw subtype badges
  (dependency-added rows included, matching the incomplete review), falling
  back to the generic Outdoor Activity badge for subtype-less journals.
- **Recent activity totals**: `src/components/journals/ActivityTotalsTable.tsx`
  — a card with an accessible table of outdoor activity counts by effective
  journal type over the rolling last-30-day and last-365-day windows shown
  together (sr-only caption, `scope='col'`/`scope='row'` headers, missing
  window counts rendered as an explicit `0`).
- **Checked-out gear**: `src/components/journals/CheckedOutGearList.tsx` — a
  card listing the gear the user has out right now (longest out first, the
  backend's ordering), each with its name and a "Checked out since {date}"
  line. Rows are **informational text with no link**: there is no per-gear-item
  page, and the spec only requires the item and its checkout date. See
  [Database Design](./database-design.md) for the "checked out" definition.
- **Templates done**: `src/components/journals/TemplatesDoneList.tsx` — a card
  grouping the templates referenced by the user's abseiling activities by
  template type (type-sorted `h4` headings, each labelling its own list), with
  a per-template done-count rendered as readable text ("Done 2 times"). Each
  template links to `/settings#templates`, matching the durable template
  reference on journal detail (`TemplateReference.tsx`) — there is no
  per-template route. Template types reuse `TYPE_LABELS` where they overlap the
  journal type enum, falling back to a capitalised raw value for `abseiling`.
- **States**: every widget owns its loading skeletons, destructive error
  alerts, and empty states, mirroring the incomplete review.

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and frontend principles
- [AI Guidelines](../ai-guidelines.md) - Frontend development standards and guidelines
- [Technology Stack](./technology-stack.md) - Frontend technology choices and frameworks
- [Domain Architecture](./domain-architecture.md) - Domain patterns for frontend integration
- [API Design](./api-design.md) - API integration patterns for frontend
- [Testing Strategy](./testing-strategy.md) - Component testing patterns and accessibility testing
- [Deployment Guide](./deployment-guide.md) - Frontend deployment configuration and Docker setup
