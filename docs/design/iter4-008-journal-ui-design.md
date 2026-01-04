# ITER4-008: Journal UI - List & Detail Views
## Detailed Design and Implementation Plan

---

## 1. Overview

This task implements the core journal UI components: **JournalList** and **JournalDetail** with inline editing capabilities. The design follows established patterns from the contacts domain, leveraging existing inline editing infrastructure and shadcn/ui components.

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| JournalList component with filtering | JournalForm (ITER4-009) |
| JournalDetail with inline editing | Calendar View (Priority 2) |
| Date grouping and pagination | MCP Tools (ITER4-010) |
| Type-specific sections | Contact Page Journal Display (ITER4-011) |
| Responsive design | Markdown editor with preview |
| Accessibility features | PDF Export |
| Unit tests | E2E Playwright tests |

---

## 2. Component Architecture

### 2.1 Component Hierarchy

```
frontend/src/
├── components/journals/
│   ├── JournalList.tsx                 # Main list component
│   ├── JournalListItem.tsx             # Individual journal card
│   ├── JournalListFilters.tsx          # Sidebar filter controls
│   ├── JournalDetail.tsx               # Detail view with inline editing
│   ├── JournalIdentityInline.tsx       # Title/date inline editing
│   ├── JournalContentInline.tsx        # Markdown content inline editing
│   ├── JournalTypeBadges.tsx           # Type badge display
│   ├── JournalTypeSection.tsx          # Collapsible type-specific section
│   ├── JournalContactsList.tsx         # Contact relationships (inline editable)
│   ├── JournalTagsList.tsx             # Tag badges (inline editable)
│   ├── JournalCalendarBadge.tsx        # Calendar indicator (inline editable)
│   ├── JournalChildrenList.tsx         # Child journals display
│   ├── JournalBreadcrumb.tsx           # Parent navigation
│   ├── InlineEditDateRange.tsx         # Date range inline editor
│   ├── InlineEditMarkdown.tsx          # Markdown inline editor
│   ├── __tests__/
│   │   ├── JournalList.test.tsx
│   │   ├── JournalListItem.test.tsx
│   │   ├── JournalDetail.test.tsx
│   │   └── ... (tests for each component)
├── types/journals.ts                   # TypeScript interfaces
└── lib/api/journals.ts                 # API hooks and functions
```

### 2.2 Data Flow

```
API (TanStack Query) → JournalList/Detail → Child Components
                                    ↓
                            useInlineEdit hook
                                    ↓
                            Mutation → API → Cache Invalidation
```

---

## 3. TypeScript Types (`frontend/src/types/journals.ts`)

### 3.1 Core Types

Define types matching backend schemas:

- **JournalType enum** - NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM
- **JournalContactRelationshipType enum** - PARTICIPANT, INVITEE, MENTION, ABOUT
- **EventDateRangeAttributes** - start, end (datetime strings)
- **JournalContactRelationship** - id, name, relationship_type
- **JournalTag** - id, name, color
- **JournalCalendar** - id, name, color
- **JournalAttributes** - title, content, event_date_range, types, type_data, contacts, tags, calendar, parent, children_count, created_at, updated_at
- **JournalResource** - type, id, attributes, relationships, links

### 3.2 Type-Specific Data Types

- **CalendarInfoData** - calendar_id, start_time, end_time, is_all_day, location, sync_invitees
- **MoodData** - mood_value, mood_label, energy_level
- **PhotoAlbumData** - immich_album_id
- **PlanData** - documents array
- **TravelData** - flights, accommodations, transportation arrays

### 3.3 Filter Types

- **JournalFilters** - date_range, types, contact_id, tag_ids, calendar_id, parent_id, search query, page, limit

---

## 4. API Layer (`frontend/src/lib/api/journals.ts`)

### 4.1 API Functions

| Function | Description |
|----------|-------------|
| `fetchJournals(filters)` | List with pagination and filters |
| `fetchJournal(id)` | Single journal with full data |
| `searchJournals(query, filters)` | MeiliSearch-powered search |
| `updateJournalField(id, field, value)` | Partial field update |
| `deleteJournal(id)` | Delete with confirmation |
| `addJournalType(id, type, data)` | Add type to journal |
| `removeJournalType(id, type)` | Remove type from journal |
| `updateJournalTypeData(id, type, data)` | Update type-specific data |
| `addContactRelationship(id, contactId, type)` | Add contact |
| `removeContactRelationship(id, contactId, type)` | Remove contact |
| `addJournalTag(id, tagId)` | Add tag |
| `removeJournalTag(id, tagId)` | Remove tag |

### 4.2 TanStack Query Hooks

| Hook | Purpose |
|------|---------|
| `useJournals(filters)` | Paginated journal list |
| `useJournal(id)` | Single journal data |
| `useSearchJournals(query, filters)` | Search results |
| `useUpdateJournalField()` | Mutation for inline edits |
| `useDeleteJournal()` | Mutation for deletion |
| `useAddJournalType()` | Type management |
| `useRemoveJournalType()` | Type management |
| `useUpdateJournalTypeData()` | Type data updates |
| `useAddContactRelationship()` | Contact management |
| `useRemoveContactRelationship()` | Contact management |
| `useAddJournalTag()` | Tag management |
| `useRemoveJournalTag()` | Tag management |
| `useJournalTags()` | Fetch available journal tags |
| `useCalendars()` | Fetch available calendars |

### 4.3 Query Key Structure

```typescript
const journalKeys = {
  all: ['journals'] as const,
  lists: () => [...journalKeys.all, 'list'] as const,
  list: (filters: JournalFilters) => [...journalKeys.lists(), filters] as const,
  details: () => [...journalKeys.all, 'detail'] as const,
  detail: (id: string) => [...journalKeys.details(), id] as const,
  search: (query: string) => [...journalKeys.all, 'search', query] as const,
};
```

---

## 5. Component Specifications

### 5.1 JournalList Component

**Purpose:** Main list view with filtering, date grouping, and pagination

**shadcn/ui Components:**
- `Card` - List container
- `ScrollArea` - Scrollable list with infinite scroll
- `Skeleton` - Loading states
- `Button` - Actions (new, filters toggle)
- `Sheet` - Mobile filter sidebar (responsive)

**Props:**
```typescript
interface JournalListProps {
  initialFilters?: JournalFilters;
  onJournalSelect?: (journalId: string) => void;
  className?: string;
}
```

**Features:**
- Infinite scroll pagination using TanStack Query's `useInfiniteQuery`
- Date grouping toggle (day/week/month) - group by `event_date_range.start`
- Responsive layout: filters sidebar on desktop, sheet on mobile
- Quick actions on hover: edit, delete, duplicate

**State Management:**
- Local state: filter panel visibility, date grouping mode, selected journal
- Server state: journal list via TanStack Query

### 5.2 JournalListFilters Component

**Purpose:** Filter controls for the journal list

**shadcn/ui Components:**
- `Calendar` (for date range picker)
- `Popover` + `Command` (for type multi-select)
- `Combobox` (for contact autocomplete - reuse `ContactSearchCombobox`)
- `Popover` + `Command` (for tag multi-select)
- `Select` (for calendar selection)
- `Checkbox` (for parent/child toggle)
- `Button` (clear filters)

**Filter Controls:**
1. **Date Range** - Calendar date picker with range mode
2. **Types** - Multi-select with checkboxes for journal types
3. **Contacts** - Autocomplete search using existing ContactSearchCombobox
4. **Tags** - Multi-select from hierarchical tag list
5. **Calendar** - Single-select dropdown
6. **Hierarchy** - Toggle for top-level only / specific parent

### 5.3 JournalListItem Component

**Purpose:** Individual journal card in the list

**shadcn/ui Components:**
- `Card`, `CardHeader`, `CardContent`
- `Badge` (for types, tags)
- `Button` (quick actions)
- `DropdownMenu` (more actions)
- `Collapsible` (expandable content)

**Visual Elements:**
- **Left edge colour bar** - Calendar colour (4px wide)
- **Type icons** - Lucide icons next to title
- **Title** - Main text, truncated if long
- **Date display** - Formatted event_date_range
- **Tag badges** - Coloured badges with tag colours
- **Contact chips** - Avatar + name for contacts
- **Content excerpt** - First 200 chars, expandable

**Layout:**
```
┌─────────────────────────────────────────────┐
│█ [type icons] Title                    [···]│
│█ 15 Dec 2025 - 16 Dec 2025                  │
│█ [tag1] [tag2] [tag3]                       │
│█ [👤 John] [👤 Jane]                        │
│█ Content excerpt that shows the first 200   │
│█ characters of the journal content...       │
└─────────────────────────────────────────────┘
```

### 5.4 JournalDetail Component

**Purpose:** Full journal detail view with inline editing

**shadcn/ui Components:**
- `Card`, `CardHeader`, `CardContent`
- `Collapsible` (for type sections)
- `Separator`
- `Badge` (types, tags)
- `Button` (actions)
- `Dialog` (delete confirmation)
- `Skeleton` (loading)
- `Alert` (errors)

**Layout Sections:**
1. **Header** - Back button, title (inline editable), actions
2. **Identity** - Title, event date range (inline editable)
3. **Metadata Bar** - Type badges, calendar badge, tags
4. **Content** - Markdown rendered, click to edit
5. **Type Sections** - Collapsible sections per type with inline editing
6. **Relationships** - Contacts grouped by relationship type
7. **Hierarchy** - Parent breadcrumb, child journals list
8. **Footer** - Created/updated timestamps

**State Management:**
- Server state: journal data via `useJournal(id)`
- Loading/error states with proper UI feedback

### 5.5 JournalIdentityInline Component

**Purpose:** Inline editing for title and date range

**Pattern:** Follow `ContactIdentityInline` pattern

**Fields:**
- **Title** - Use existing `InlineEditField`
- **Date Range** - New `InlineEditDateRange` component

### 5.6 InlineEditDateRange Component

**Purpose:** Click-to-edit for date ranges

**shadcn/ui Components:**
- `Popover`
- `Calendar` with range mode
- `Button` (trigger, save, cancel)

**Behaviour:**
- View mode: Display formatted date range
- Edit mode: Popover with dual-month calendar
- Validation: Start <= End
- Optimistic updates using `useInlineEdit` pattern

---


### 5.7 JournalContentInline Component

**Purpose:** Inline editing for markdown content

**Behaviour:**
- View mode: Rendered markdown using `marked.js` (or similar)
- Edit mode: Textarea with markdown preview toggle
- Debounced auto-save (optional, consider for later)

**shadcn/ui Components:**
- `Textarea`
- `Tabs` (edit/preview toggle)
- `Button` (save, cancel)

### 5.8 JournalTypeSection Component

**Purpose:** Collapsible section for type-specific data

**shadcn/ui Components:**
- `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent`
- `Card` (section container)
- Various inline edit fields for type data

**Type-Specific Content:**

| Type | Editable Fields |
|------|-----------------|
| EVENT | Calendar select, times, location, all-day toggle |
| MOOD_RATING | Mood value (slider 1-10), mood label, energy level (slider 1-10) |
| PHOTO_ALBUM | Immich album ID (text input, future: album picker) |
| PLAN | Document list (add/remove/reorder) |
| TRAVEL | Flights, accommodations, transportation lists |

### 5.9 JournalContactsList Component

**Purpose:** Display and manage contact relationships

**shadcn/ui Components:**
- `Badge` (relationship type)
- `Button` (add, remove)
- `Popover` + `Command` (add contact)
- `Dialog` (confirm removal)

**Grouping:** Organise contacts by relationship type (PARTICIPANT, INVITEE, ABOUT, MENTION)

**Inline Editing:**
- Add contact: Combobox with contact search
- Remove contact: Click X on contact chip
- Change relationship type: Dropdown on contact chip

### 5.10 JournalTagsList Component

**Purpose:** Display and manage journal tags

**shadcn/ui Components:**
- `Badge` (tag with colour)
- `Button` (add)
- `Popover` + `Command` (add tag)

**Behaviour:**
- Display tags as coloured badges
- Click to filter list by tag
- Add/remove tags with popover selector

### 5.11 JournalCalendarBadge Component

**Purpose:** Display calendar assignment with inline editing

**shadcn/ui Components:**
- `Badge` (calendar with colour)
- `Popover` + `Select` (change calendar)

**Behaviour:**
- Show calendar name with colour indicator
- Click to change calendar (only for EVENT type journals)

### 5.12 JournalChildrenList Component

**Purpose:** Display child journals

**shadcn/ui Components:**
- `Card` (child journal cards)
- `Collapsible` (expandable child content)
- `Button` (add child)

**Display:**
- List children sorted by event_date_range, then order
- Show as condensed cards with title, date, excerpt
- Link to child detail view

### 5.13 JournalBreadcrumb Component

**Purpose:** Navigate parent hierarchy

**shadcn/ui Components:**
- Custom breadcrumb using `Button` links
- Lucide `ChevronRight` separator

**Display:** `Home > Parent Title > Current Title`

---

## 6. Reusable Components & Hooks

### 6.1 Existing Components to Reuse

| Component | From | Usage |
|-----------|------|-------|
| `InlineEditField` | contacts | Base inline editing |
| `useInlineEdit` | hooks | Edit state management |
| `ContactSearchCombobox` | contacts | Contact autocomplete |
| `Skeleton` patterns | contacts | Loading states |

### 6.2 New Shared Components

| Component | Purpose |
|-----------|---------|
| `InlineEditDateRange` | Date range inline editing |
| `InlineEditMarkdown` | Markdown content editing |
| `InlineEditSlider` | Numeric slider (1-10) editing |
| `TypeIcon` | Icon mapping for journal types |
| `ColourBadge` | Badge with background colour |

### 6.3 Icon Mapping for Journal Types

| Type | Lucide Icon |
|------|-------------|
| NOTE | `FileText` |
| EVENT | `Calendar` |
| MOOD_RATING | `Heart` or `Smile` |
| PLAN | `ClipboardList` |
| TRAVEL | `Plane` |
| PHOTO_ALBUM | `Image` |

---

## 7. Responsive Design

### 7.1 Breakpoints

| Breakpoint | Layout |
|------------|--------|
| Mobile (`<sm`) | Single column, stacked filters in Sheet |
| Tablet (`sm-lg`) | Two columns, collapsible sidebar |
| Desktop (`lg+`) | Three columns with persistent sidebar |

### 7.2 JournalList Responsive Behaviour

- **Mobile:** Full-width list, filter button opens Sheet
- **Desktop:** Sidebar filters (300px), list takes remaining width

### 7.3 JournalDetail Responsive Behaviour

- **Mobile:** Single column, stacked sections
- **Desktop:** Main content (2/3), sidebar metadata (1/3)

---

## 8. Accessibility Requirements

### 8.1 ARIA Attributes

- All interactive elements have `aria-label`
- Collapsible sections use `aria-expanded`
- Inline edit fields have proper `aria-describedby` for errors
- Filter controls have associated labels

### 8.2 Keyboard Navigation

- Tab through all interactive elements
- Enter/Space to activate buttons and toggles
- Escape to cancel inline editing
- Arrow keys for list navigation (future enhancement)

### 8.3 Screen Reader Support

- `sr-only` labels for icon-only buttons
- Announce changes when content updates
- Descriptive link text (not "click here")


---

## 9. Testing Strategy

### 9.1 Unit Tests (Jest)

**For each component test:**
- Renders correctly with minimal props
- Renders loading state
- Renders error state
- Renders with full data

**JournalList tests:**
- Displays list of journals
- Shows empty state when no journals
- Filters update query
- Pagination loads more items

**JournalDetail tests:**
- Displays all journal information
- Inline edit triggers on click
- Type sections collapse/expand
- Delete confirmation works

**Inline edit component tests:**
- View mode displays value
- Click enters edit mode
- Escape cancels editing
- Enter saves changes
- Validation errors display

### 9.2 React Testing Library Patterns

```typescript
// Example test structure
describe('JournalListItem', () => {
  it('displays journal title and date', () => {
    render(<JournalListItem journal={mockJournal} />);
    expect(screen.getByText('Test Journal')).toBeInTheDocument();
    expect(screen.getByText('15 Dec 2025')).toBeInTheDocument();
  });

  it('shows type badges', () => {
    render(<JournalListItem journal={journalWithTypes} />);
    expect(screen.getByText('EVENT')).toBeInTheDocument();
  });
});
```

### 9.3 Mock Data

Create mock factories for:
- `createMockJournal(overrides)`
- `createMockJournalList(count, overrides)`
- `createMockCalendar(overrides)`
- `createMockJournalTag(overrides)`

---

## 10. Implementation Order

### Phase 1: Foundation (Files 1-4)

1. **Types** - `types/journals.ts`
2. **API Layer** - `lib/api/journals.ts`
3. **JournalListItem** - Basic card display
4. **JournalList** - List with pagination

### Phase 2: Detail View (Files 5-8)

5. **JournalDetail** - Main detail layout
6. **JournalIdentityInline** - Title/date editing
7. **JournalContentInline** - Markdown editing (simple textarea first)
8. **InlineEditDateRange** - Date range picker

### Phase 3: Type Sections (Files 9-11)

9. **JournalTypeBadges** - Type display
10. **JournalTypeSection** - Collapsible type sections
11. **Type-specific editors** (EVENT, MOOD_RATING, PHOTO_ALBUM)

### Phase 4: Relationships (Files 12-15)

12. **JournalContactsList** - Contact management
13. **JournalTagsList** - Tag management
14. **JournalCalendarBadge** - Calendar display/editing
15. **JournalBreadcrumb** - Parent navigation

### Phase 5: Hierarchy & Filters (Files 16-18)

16. **JournalChildrenList** - Child journals
17. **JournalListFilters** - Filter sidebar
18. **Integration** - Wire up all components

### Phase 6: Polish & Tests (Files 19-20+)

19. **Responsive polish**
20. **Comprehensive tests for all components**

---

## 11. Dependencies

### 11.1 Required NPM Packages (Verify Installed)

- `@tanstack/react-query` - Server state
- `date-fns` - Date formatting
- `lucide-react` - Icons
- `zod` - Validation
- `react-hook-form` - Form management
- `marked` or `react-markdown` - Markdown rendering (may need to add)

### 11.2 shadcn/ui Components to Verify/Add

Check if these are installed, add if needed:
- ✅ `Card`, `Badge`, `Button`, `Skeleton`, `Dialog`
- ✅ `Popover`, `Command`, `Calendar`, `Select`
- ❓ `Collapsible` - May need to add
- ❓ `Tabs` - May need to add
- ❓ `ScrollArea` - May need to add
- ❓ `Sheet` - May need to add

---

## 12. Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| JournalList renders with data | Unit test passes |
| Filters update list results | Integration test |
| Inline editing saves correctly | Unit test with mocked API |
| Responsive layout works | Visual verification |
| Accessibility meets standards | axe audit passes |
| All unit tests pass | CI pipeline |
| Type safety verified | TypeScript compilation |
| Loading/error states display | Unit tests |

---

## 13. Risk Considerations

| Risk | Mitigation |
|------|------------|
| Complex type-specific forms | Start with simple text inputs, enhance later |
| Markdown editor complexity | Use simple textarea first, add preview toggle |
| Performance with large lists | Implement virtualisation if needed (future) |
| Date picker timezone issues | Use consistent UTC handling from backend |

---

## 14. Out of Scope (Deferred to Future Tasks)

- Drag-and-drop child reordering
- Calendar view (separate future task)
- PDF export
- Advanced markdown editor with toolbar
- Immich album picker integration
- GPX track display for travel journals
- E2E Playwright tests (separate testing task)

---

## 15. Implementation Status

### Phase 1: Foundation (Files 1-4) ✅ COMPLETE

**Completed:** 2026-01-04

**Files Implemented:**
1. ✅ **Types** - `frontend/src/types/journals.ts`
2. ✅ **API Layer** - `frontend/src/lib/api/journals.ts`
3. ✅ **JournalListItem** - `frontend/src/components/journals/JournalListItem.tsx`
4. ✅ **JournalList** - `frontend/src/components/journals/JournalList.tsx`
5. ✅ **JournalFilters** - `frontend/src/components/journals/JournalFilters.tsx` (from Phase 5, implemented early)

#### Implemented Components

1. **TypeScript Types** (`frontend/src/types/journals.ts`)
   - ✅ `JournalType` enum (NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM)
   - ✅ `JournalContactRelationshipType` enum (PARTICIPANT, INVITEE, MENTION, ABOUT)
   - ✅ `EventDateRange` interface
   - ✅ `JournalContactRelationship` interface
   - ✅ `JournalTag` interface
   - ✅ `JournalCalendar` interface
   - ✅ `JournalAttributes` interface with all required fields
   - ✅ `JournalResource` interface
   - ✅ Type-specific data types (MoodRatingData, TravelData, PhotoAlbumData, PlanData, CalendarInfoData)
   - ✅ `JournalFilters` interface
   - ✅ `JournalFormData` interface
   - ✅ Response types (JournalResponse, JournalListResponse)

2. **API Layer** (`frontend/src/lib/api/journals.ts`)
   - ✅ Query hooks:
     - `useJournals(filters)` - Fetch journals with filtering
     - `useJournal(id)` - Fetch single journal
     - `useSearchJournals(query)` - Search journals
     - `useJournalTags()` - Fetch available tags
   - ✅ Mutation hooks:
     - `useCreateJournal()` - Create new journal
     - `useUpdateJournal()` - Update journal
     - `useDeleteJournal()` - Delete journal
     - `useUpdateJournalField()` - Update single field
   - ✅ Type management hooks:
     - `useAddJournalType()` - Add type to journal
     - `useRemoveJournalType()` - Remove type from journal
   - ✅ Relationship management hooks:
     - `useAddContactRelationship()` - Add contact relationship
     - `useRemoveContactRelationship()` - Remove contact relationship
     - `useAddJournalTag()` - Add tag to journal
     - `useRemoveJournalTag()` - Remove tag from journal
   - ✅ Query key structure for proper cache management
   - ✅ Error handling with toast notifications
   - ✅ Optimistic updates and cache invalidation

3. **Components**
   - ✅ `JournalListItem` (`frontend/src/components/journals/JournalListItem.tsx`)
     - Calendar color bar on left edge
     - Type icons (FileText, Calendar, Heart, ClipboardList, Plane, Image)
     - Title as clickable link to detail page
     - Date range display with Australian formatting
     - Tag badges with colors
     - Contact chips with relationship types
     - Content excerpt with truncation
   - ✅ `JournalList` (`frontend/src/components/journals/JournalList.tsx`)
     - Responsive grid layout (1/2/3 columns)
     - Empty state support
     - Renders JournalListItem components
   - ✅ `JournalFilters` (`frontend/src/components/journals/JournalFilters.tsx`)
     - Date range picker with calendar component
     - Journal type checkboxes (all 6 types)
     - Contact search using ContactSearchCombobox
     - Tag multi-select with checkboxes
     - Calendar selection dropdown
     - Clear all filters button
     - Active filter state management

4. **Unit Tests**
   - ✅ Type tests (`frontend/src/types/__tests__/journals.test.ts`)
   - ✅ API tests (`frontend/src/lib/api/__tests__/journals.test.ts`)
   - ✅ Component tests:
     - `JournalListItem.test.tsx`
     - `JournalList.test.tsx`
     - `JournalFilters.test.tsx`

5. **Supporting Files**
   - ✅ Updated `frontend/src/lib/constants.ts` with journal endpoints and messages
   - ✅ Created journal detail page route (`frontend/src/app/journals/[id]/page.tsx`)

#### Quality Assurance

- ✅ All formatting checks pass (Prettier)
- ✅ All linting checks pass (ESLint)
- ✅ All type checks pass (TypeScript)
- ✅ All unit tests pass (Jest)
- ✅ Code follows established patterns from contacts domain
- ✅ Accessibility attributes included (aria-labels, test-ids)
- ✅ Responsive design implemented

#### Notes

- Components follow the established inline editing pattern from contacts domain
- API layer uses TanStack Query for caching and optimistic updates
- All components are properly typed with TypeScript
- Date formatting uses Australian locale (enAU) consistently
- Calendar color bar provides visual distinction between calendars
- Type icons provide quick visual identification of journal types
- JournalFilters was implemented early (originally planned for Phase 5)

### Phase 2: Detail View (Files 5-8) ⏳ PENDING

**Status:** Not started

**Planned Files:**
- [ ] 5. **JournalDetail** - `frontend/src/components/journals/JournalDetail.tsx` - Main detail layout
- [ ] 6. **JournalIdentityInline** - `frontend/src/components/journals/JournalIdentityInline.tsx` - Title/date editing
- [ ] 7. **JournalContentInline** - `frontend/src/components/journals/JournalContentInline.tsx` - Markdown editing (simple textarea first)
- [ ] 8. **InlineEditDateRange** - `frontend/src/components/journals/InlineEditDateRange.tsx` - Date range picker

### Phase 3: Type Sections (Files 9-11) ⏳ PENDING

**Status:** Not started

**Planned Files:**
- [ ] 9. **JournalTypeBadges** - `frontend/src/components/journals/JournalTypeBadges.tsx` - Type display
- [ ] 10. **JournalTypeSection** - `frontend/src/components/journals/JournalTypeSection.tsx` - Collapsible type sections
- [ ] 11. **Type-specific editors** - Type-specific form components (EVENT, MOOD_RATING, PHOTO_ALBUM)

### Phase 4: Relationships (Files 12-15) ⏳ PENDING

**Status:** Not started

**Planned Files:**
- [ ] 12. **JournalContactsList** - `frontend/src/components/journals/JournalContactsList.tsx` - Contact management
- [ ] 13. **JournalTagsList** - `frontend/src/components/journals/JournalTagsList.tsx` - Tag management
- [ ] 14. **JournalCalendarBadge** - `frontend/src/components/journals/JournalCalendarBadge.tsx` - Calendar display/editing
- [ ] 15. **JournalBreadcrumb** - `frontend/src/components/journals/JournalBreadcrumb.tsx` - Parent navigation

### Phase 5: Hierarchy & Filters (Files 16-18) ⏳ PENDING

**Status:** Partially complete (JournalFilters implemented in Phase 1)

**Planned Files:**
- [ ] 16. **JournalChildrenList** - `frontend/src/components/journals/JournalChildrenList.tsx` - Child journals
- [x] 17. **JournalListFilters** - `frontend/src/components/journals/JournalFilters.tsx` - Filter sidebar (COMPLETE)
- [ ] 18. **Integration** - Wire up all components

### Phase 6: Polish & Tests (Files 19-20+) ⏳ PENDING

**Status:** Not started

**Planned Work:**
- [ ] 19. **Responsive polish** - Mobile/tablet optimizations
- [ ] 20. **Comprehensive tests** - Integration tests for all components
- [ ] **Advanced features:**
  - Infinite scroll pagination
  - Date grouping in list view
  - Performance optimizations
  - Quick actions (edit, delete, duplicate)