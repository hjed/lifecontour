# Iteration 2.5: Interactive Contact Editing

**Status:** 🟡 PLANNED
**Goal:** Transform contact view/edit screen into a powerful, interactive interface with inline field editing capabilities

## Overview

This iteration enhances the contact detail page with modern inline editing functionality, allowing users to edit individual fields directly without entering a full edit mode. Each field becomes clickable for editing with immediate save/cancel options, providing a more intuitive and efficient user experience.

![Contact Screen Design](contact-screen-design.png)

## Key Features

### Interactive Field Editing
- **Click-to-Edit Fields**: Transform static display fields into interactive edit zones
- **Individual Field States**: Each field manages its own edit/view state independently
- **Immediate Actions**: Save (✅) and cancel (❌) buttons for each field during editing
- **Optimistic Updates**: Immediate UI feedback with rollback on errors
- **Field-Specific Validation**: Real-time validation for each field type

### Enhanced Layout & Visual Design
- **Profile Picture Display**: Large avatar/profile picture with placeholder for contacts without photos
- **Improved Header Layout**: Contact name, tags, and metadata with profile picture integration
- **Three-Column Layout**: Profile picture, contact details, and activity/relationships sidebar
- **Visual Hierarchy**: Clear separation between different information sections

### Relationships Management
- **Contact Relationships**: Partner, children, family, and professional relationships
- **Relationship Types**: Configurable relationship categories with bidirectional linking
- **Inline Relationship Editing**: Add, edit, and remove relationships directly from contact view
- **Relationship Validation**: Prevent circular references and maintain data integrity

### Activity Feed & History
- **Field-Level Activity Tracking**: Detailed history of all field changes with timestamps
- **Event-Based Activity**: Integration with existing contact history service
- **Activity Categories**: Contact updates, relationship changes, tag modifications
- **Load More Functionality**: Paginated activity feed with infinite scroll

### Enhanced User Experience
- **Contextual Icons**: Visual indicators for different field types (email, phone, address)
- **Responsive Design**: Consistent behavior across desktop and mobile devices
- **Accessibility**: Full keyboard navigation and screen reader support
- **Loading States**: Clear feedback during save operations

### Backend Enhancements
- **Partial Update Endpoints**: PATCH endpoints for individual field updates
- **Relationship Management**: Backend support for contact relationships
- **Enhanced Activity Tracking**: Expanded contact history service integration
- **Field-Specific Validation**: Granular validation logic for different field types
- **Optimized Queries**: Efficient database operations for single field updates

## Architecture Alignment

This iteration follows established patterns:
- **Domain-Driven Design**: Contact domain handles all business logic
- **Ports & Adapters**: Clean separation between UI, API, and domain layers
- **Event-Driven Updates**: MeiliSearch indexing via outbox pattern
- **Test-First Development**: Comprehensive test coverage at all layers
- **shadcn/ui Components**: Consistent design system usage

## Task Breakdown

### Task 2.5A: Backend Infrastructure & Relationships
**Estimated Effort:** 3-4 hours
**Files Changed:** ~12 files

#### Backend Changes
- Add PATCH endpoint for individual field updates (`/api/contacts/{id}/fields/{field_name}`)
- Create contact relationships data model and database schema
- Implement relationship management endpoints (`/api/contacts/{id}/relationships`)
- Enhance contact history service for detailed activity tracking
- Add field-specific validation schemas and request models

#### Testing
- Unit tests for relationship validation logic
- Integration tests for PATCH endpoints and relationship management
- Database transaction tests for partial updates

### Task 2.5B: Profile Picture & Layout Enhancement
**Estimated Effort:** 2-3 hours
**Files Changed:** ~6 files
**Status:** 🟡 IN PROGRESS

#### Implementation Steps

**Step 1: ContactAvatar Component** ✅ COMPLETE
- Built on shadcn/ui Avatar components with intelligent initials generation
- Supports multiple sizes (sm, md, lg) and custom styling
- Handles edge cases and future image URL integration
- 18 comprehensive test cases, all passing

**Step 2: ContactHeader Component** ✅ COMPLETE
- Integrates ContactAvatar and FavouriteToggle components
- Displays contact name with nickname using proper HTML entities
- Shows tags as badges with correct TagResource structure
- 20 comprehensive test cases, all passing

**Step 3: Architecture Refactoring** 🔄 IN PROGRESS
- **Step 3A**: Extract shared utilities and create ContactIdentity component
- **Step 3B**: Implement page-level CSS Grid three-column layout
- **Step 3C**: Update tests for new component structure

**Step 4: Responsive Design** 🔄 PLANNED
- Mobile-first approach with proper stacking on small screens
- Tablet and desktop optimizations for three-column display

**Step 5: Integration Testing** 🔄 PLANNED
- Test with various contact data scenarios
- Ensure accessibility compliance across all breakpoints

#### Technical Notes
- Leverages existing shadcn/ui Avatar, AvatarImage, and AvatarFallback components
- ContactAvatar component handles initials generation (e.g., "John Doe" → "JD")
- Supports different sizes and future image URL integration
- Built-in fallback behavior when images fail to load
- Three-column layout: Profile picture, contact details, activity/relationships sidebar

#### Testing
- Component tests for avatar display and layout
- Responsive design tests across breakpoints
- Accessibility tests for new layout structure
- Tests for initials generation logic

### Task 2.5C: Frontend Inline Editing Components
**Estimated Effort:** 3-4 hours
**Files Changed:** ~10 files

#### Frontend Changes
- Create `InlineEditField` component with edit/view states
- Implement field-specific editors (text, email, phone, address)
- Add optimistic update logic with error handling
- Create field-specific validation and formatting

#### Testing
- Component tests for inline editing behavior
- User interaction tests (click, edit, save, cancel)
- Accessibility tests for keyboard navigation

### Task 2.5D: Relationships Management UI
**Estimated Effort:** 3-4 hours
**Files Changed:** ~8 files

#### Implementation
- Create relationships section with inline editing
- Implement relationship type selection and validation
- Add relationship search and linking functionality
- Create relationship management components (add, edit, remove)

#### Testing
- Relationship component tests
- Relationship validation and linking tests
- User interaction tests for relationship management

### Task 2.5E: Activity Feed Implementation
**Estimated Effort:** 2-3 hours
**Files Changed:** ~6 files

#### Implementation
- Create activity feed component with timeline display
- Integrate with existing contact history service
- Implement activity categorization and formatting
- Add "Load More" functionality with pagination

#### Testing
- Activity feed component tests
- Integration tests with contact history service
- Pagination and loading state tests

### Task 2.5F: Contact Methods & Address Inline Editing
**Estimated Effort:** 2-3 hours
**Files Changed:** ~6 files

#### Implementation
- Inline editing for email addresses with validation
- Inline editing for phone numbers with formatting
- Multi-line address editing with structured format
- Add/remove functionality for methods and addresses

#### Testing
- Contact method and address validation tests
- Primary designation constraint tests
- Add/remove functionality tests

### Task 2.5G: Integration & Polish
**Estimated Effort:** 2 hours
**Files Changed:** ~4 files

#### Implementation
- Integrate all components into enhanced contact detail page
- Add loading states and error handling throughout
- Implement bulk save functionality for multiple edits
- Performance optimization and final polish

#### Testing
- End-to-end tests for complete editing workflows
- Integration tests for all new functionality
- Performance tests for multiple simultaneous edits

### Task 2.5H: MCP Server Integration
**Estimated Effort:** 1-2 hours
**Files Changed:** ~3 files

#### Implementation
- Update MCP (Model Context Protocol) server to expose new PATCH endpoints
- Add field update endpoints to MCP API interface:
  - Basic contact field updates (`/api/contacts/{id}/fields/{field_name}`)
  - Contact method field updates (`/api/contacts/{id}/methods/{method_id}/fields/{field_name}`)
  - Contact address field updates (`/api/contacts/{id}/addresses/{address_id}/fields/{field_name}`)
  - Contact note field updates (`/api/contacts/{id}/notes/{note_id}/fields/{field_name}`)
- Ensure proper request/response schema mapping for MCP protocol
- Update MCP documentation and examples

#### Testing
- MCP endpoint integration tests
- Protocol compliance validation
- Request/response schema verification

## Technical Implementation Details

### Backend API Design

```python
# New PATCH endpoint for field updates
@router.patch("/{contact_id}/fields/{field_name}")
async def update_contact_field(
    contact_id: int,
    field_name: str,
    field_update: FieldUpdateRequest,
    contact_service: FromDishka[ContactService],
) -> ContactFieldResponse:
    """Update a specific contact field."""
```

### Frontend Component Structure

```typescript
// Inline edit field component
interface InlineEditFieldProps {
  value: string;
  fieldType: 'text' | 'email' | 'phone' | 'address';
  onSave: (value: string) => Promise<void>;
  validation?: (value: string) => string | null;
  placeholder?: string;
}

// Contact relationships component
interface ContactRelationshipProps {
  contactId: string;
  relationships: ContactRelationship[];
  onAdd: (relationship: ContactRelationship) => Promise<void>;
  onUpdate: (id: string, relationship: ContactRelationship) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
}

// Activity feed component
interface ActivityFeedProps {
  contactId: string;
  activities: ContactActivity[];
  onLoadMore: () => Promise<void>;
  hasMore: boolean;
  isLoading: boolean;
}
```

### Database Considerations

- Leverage existing contact update infrastructure
- Maintain referential integrity for related entities
- Ensure proper indexing for field-specific queries
- Preserve audit trail through existing event system

## Quality Standards

### Test Coverage Requirements
- **Backend**: 95%+ coverage for new endpoints and services
- **Frontend**: 90%+ coverage for new components and hooks
- **E2E**: Complete user workflows tested with Playwright

### Performance Targets
- **Field Update Response**: < 200ms for individual field saves
- **UI Responsiveness**: < 100ms for edit mode transitions
- **Optimistic Updates**: Immediate UI feedback with proper rollback

### Accessibility Standards
- Full keyboard navigation support
- Screen reader compatibility
- WCAG 2.1 AA compliance
- Focus management during edit transitions

## Dependencies & Constraints

### Prerequisites
- Iteration 2 (Integration Architecture) completion
- Current contact management functionality
- Existing shadcn/ui component library

### External Dependencies
- No new external dependencies required
- Leverages existing validation libraries
- Uses established API patterns

## Success Criteria

### User Experience

- ✅ Users can edit any contact field by clicking on it
- ✅ Each field shows clear save/cancel options during editing
- ✅ Profile picture displays prominently with placeholder support
- ✅ Relationships section allows easy management of contact connections
- ✅ Activity feed shows comprehensive history of contact changes
- ✅ Changes are saved immediately with visual feedback
- ✅ Errors are handled gracefully with clear messaging
- ✅ Interface remains responsive and intuitive across all devices

### Technical Quality

- ✅ All tests pass with required coverage levels
- ✅ No performance regressions in contact loading
- ✅ Proper error handling and rollback mechanisms
- ✅ Clean, maintainable code following established patterns
- ✅ Full accessibility compliance
- ✅ Relationship data integrity maintained
- ✅ Activity tracking captures all field-level modifications

### Integration

- ✅ MeiliSearch indexing updates correctly for field changes
- ✅ Activity tracking integrates with existing contact history service
- ✅ Relationship management works seamlessly with contact data
- ✅ Existing contact functionality remains unaffected
- ✅ Mobile and desktop experiences are consistent
- ✅ Profile pictures integrate with future Immich photo matching

## Future Enhancements

This iteration establishes the foundation for:

- Bulk editing capabilities across multiple contacts
- Advanced field types (custom fields, rich text)
- Real-time collaborative editing
- Field-level permissions and access controls
- Integration with external data sources for field validation
- Advanced relationship types and family tree visualization
- Photo integration with Immich for profile pictures
- Calendar integration for relationship-based event tracking

---

*This iteration delivers a modern, interactive contact editing experience while maintaining the system's architectural integrity and quality standards.*
