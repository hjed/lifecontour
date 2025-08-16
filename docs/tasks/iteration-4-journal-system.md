# Iteration 4: Journal System

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 3 (Extended Integrations)
**Goal:** Build comprehensive journal system with integration-powered content and AI-assisted insights

## Overview

This iteration creates a rich journaling experience that leverages all integrated data:
- Core journal domain with rich text editing and mood tracking
- Automatic journal entries from Strava activities and other integrations
- Photo album linking and visual storytelling
- AI-powered insights and sentiment analysis
- Advanced search across journal content with MeiliSearch
- MCP tools for AI-assisted journaling and reflection

## Prerequisites

- Iteration 3 completed (Immich, Strava, Firefly III integrations)
- Integration architecture with ARQ workers established
- Dishka dependency injection framework in use
- MeiliSearch indexing infrastructure available

## Tasks

### ITER4-001: Journal Domain Core 🟡 PLANNED
**Description:** Build journal domain with rich content support and mood tracking
**Strategy:** Break into 3 slices for domain, persistence, and business logic

#### Slice 1: Domain Models & Database Schema 🟡 PLANNED
**PR Size:** ~5 files (Domain entities, database migration, core models, tests)

**Acceptance Criteria:**
- [ ] Create `Journal` domain entity in core_shared with rich text content support
- [ ] Implement `JournalEntry` with mood tracking, tags, and metadata
- [ ] Add `JournalMood` enum for standardized mood tracking
- [ ] Create database schema for journal entries with full-text search support
- [ ] Implement journal entry versioning for edit history
- [ ] Add foreign key relationships to albums, activities, and transactions
- [ ] Write unit tests for domain entities and business rules
- [ ] Create database migration with proper indexes for search and filtering

**Domain Model Features:**
- Rich text content with markdown support
- Mood tracking with predefined scales
- Tag system integration for categorization
- Automatic timestamps and versioning
- Integration linking (photos, activities, transactions)

#### Slice 2: Repository & Persistence Layer 🟡 PLANNED
**PR Size:** ~4 files (Repository interfaces, SQL implementation, tests)

**Acceptance Criteria:**
- [ ] Create `JournalRepository` interface following established patterns
- [ ] Implement `SqlJournalRepository` using SQLAlchemy Core with explicit SQL
- [ ] Add journal entry CRUD operations with transaction support
- [ ] Implement advanced filtering (date ranges, moods, tags, linked content)
- [ ] Add full-text search capabilities for journal content
- [ ] Create journal statistics and analytics queries
- [ ] Write integration tests with real PostgreSQL database
- [ ] Implement proper error handling and constraint validation

#### Slice 3: Journal Service & Business Logic 🟡 PLANNED
**PR Size:** ~5 files (Service layer, validation, domain events, tests)

**Acceptance Criteria:**
- [ ] Create `JournalService` using Dishka dependency injection
- [ ] Implement journal entry creation, updating, and deletion with validation
- [ ] Add automatic integration content linking (activities, photos, transactions)
- [ ] Create mood analysis and sentiment tracking features
- [ ] Implement journal entry templates and prompts
- [ ] Add domain events for journal operations (JournalEntryCreated, Updated, etc.)
- [ ] Write comprehensive unit tests for business logic
- [ ] Integrate with outbox pattern for MeiliSearch indexing

### ITER4-002: Journal REST API with Search 🟡 PLANNED
**Description:** Create comprehensive API endpoints with advanced search capabilities
**Strategy:** Single focused task for API layer implementation

**PR Size:** ~6 files (API controllers, schemas, search integration, tests)

**Acceptance Criteria:**
- [ ] Create `JournalController` with JSON API compliant endpoints
- [ ] Implement CRUD operations for journal entries with proper validation
- [ ] Add mood tracking and analytics endpoints
- [ ] Implement MeiliSearch-powered journal search (`/api/journal/search`)
- [ ] Add journal entries to global search index with proper faceting
- [ ] Create journal statistics and insights endpoints
- [ ] Add integration content linking endpoints (albums, activities, transactions)
- [ ] Implement journal export functionality (PDF, markdown, JSON)
- [ ] Generate comprehensive OpenAPI documentation
- [ ] Write integration tests for all endpoints including search functionality

**API Endpoints:**
- `GET /api/journal/entries` - List journal entries with filtering
- `POST /api/journal/entries` - Create new journal entry
- `GET /api/journal/entries/{id}` - Get specific journal entry
- `PUT /api/journal/entries/{id}` - Update journal entry
- `DELETE /api/journal/entries/{id}` - Delete journal entry
- `GET /api/journal/search` - Search journal entries with MeiliSearch
- `GET /api/journal/moods` - Mood tracking analytics
- `GET /api/journal/insights` - AI-powered insights and trends
- `POST /api/journal/entries/{id}/link` - Link integration content

### ITER4-003: Journal UI with Rich Editor 🔴 PLANNED
**Description:** Build comprehensive journal interface with rich text editing
**Strategy:** Break into 3 slices for editor, views, and integration features

#### Slice 1: Rich Text Editor & Core UI 🟡 PLANNED
**PR Size:** ~6 files (Editor component, entry forms, basic views, tests)

**Acceptance Criteria:**
- [ ] Implement rich text editor using TipTap or similar React editor
- [ ] Create journal entry creation and editing forms with validation
- [ ] Add mood tracking interface with visual mood selectors
- [ ] Implement tag management integration with existing tag system
- [ ] Create journal entry list view with filtering and sorting
- [ ] Add responsive design for mobile and desktop journaling
- [ ] Write Jest unit tests for editor components and functionality
- [ ] Implement auto-save functionality for draft entries

#### Slice 2: Search & Analytics Dashboard 🟡 PLANNED
**PR Size:** ~5 files (Search components, analytics views, charts, tests)

**Acceptance Criteria:**
- [ ] Create journal search interface with MeiliSearch integration
- [ ] Implement advanced filtering (date ranges, moods, tags, linked content)
- [ ] Add search result highlighting for journal content
- [ ] Create mood analytics dashboard with trend visualization
- [ ] Implement journal statistics (word counts, entry frequency, mood patterns)
- [ ] Add journal insights and reflection prompts
- [ ] Create calendar view for journal entries
- [ ] Write comprehensive component tests for search and analytics

#### Slice 3: Integration Content & Visual Features 🟡 PLANNED
**PR Size:** ~5 files (Integration linking, photo galleries, activity displays, tests)

**Acceptance Criteria:**
- [ ] Implement photo album linking and gallery display in entries
- [ ] Add Strava activity integration with automatic entry creation
- [ ] Create transaction linking for financial context in entries
- [ ] Implement visual timeline view for journal entries
- [ ] Add journal entry templates based on integration data
- [ ] Create sharing and export functionality
- [ ] Implement journal entry collaboration features
- [ ] Write Playwright e2e tests for complete journaling workflows

### ITER4-004: Journal MCP Tools 🟡 PLANNED
**Description:** Add comprehensive journal management and AI assistance tools
**Strategy:** Single focused task for MCP integration

**PR Size:** ~5 files (MCP tools, AI integration, analysis tools, tests)

**Acceptance Criteria:**
- [ ] Implement journal entry creation and management tools via MCP
- [ ] Add journal search tools with mood, date, and content filtering
- [ ] Create mood analysis and sentiment tracking tools
- [ ] Implement journal insights and pattern recognition tools
- [ ] Add automatic journal prompts and reflection questions
- [ ] Create journal entry summarization and analysis tools
- [ ] Implement integration-based journal suggestions (activities, photos, etc.)
- [ ] Add journal analytics and trend analysis tools
- [ ] Write comprehensive MCP integration tests
- [ ] Document journal MCP capabilities for AI assistants

**MCP Tools to Implement:**
- `create_journal_entry()` - Create new journal entry with AI assistance
- `search_journal()` - Search journal entries with advanced filtering
- `analyze_mood_trends()` - Mood pattern analysis and insights
- `get_journal_insights()` - AI-powered insights and reflections
- `suggest_journal_prompts()` - Context-aware writing prompts
- `summarize_journal_period()` - Summarize journal entries for time periods
- `link_integration_content()` - Suggest content linking from integrations
- `export_journal_data()` - Export journal entries in various formats

### ITER4-005: Automatic Content Generation 🟡 PLANNED
**Description:** Implement AI-powered automatic journal content from integrations
**Strategy:** Single task for automation and AI features

**PR Size:** ~6 files (Content generators, AI integration, automation, tests)

**Acceptance Criteria:**
- [ ] Create automatic journal entries from Strava activities
- [ ] Implement photo-based journal entry suggestions
- [ ] Add transaction-based spending reflection prompts
- [ ] Create weekly/monthly journal summaries from integration data
- [ ] Implement mood prediction based on activity and spending patterns
- [ ] Add AI-powered writing assistance and suggestions
- [ ] Create automatic tagging based on content analysis
- [ ] Implement journal entry quality scoring and improvement suggestions
- [ ] Write integration tests for automatic content generation
- [ ] Add configuration options for automation preferences

## Architecture Notes

- **Domain Design:** Rich domain entities with business logic and validation
- **Dependency Injection:** Full Dishka integration following established patterns
- **Rich Text:** Modern editor with markdown support and extensibility
- **Search Integration:** MeiliSearch with faceted search and highlighting
- **AI Integration:** MCP tools for AI-assisted journaling and insights
- **Integration Linking:** Automatic content suggestions from all integrated services
- **Mobile Support:** Responsive design optimized for mobile journaling
- **Performance:** Efficient pagination and lazy loading for large journal collections

## Integration Features

- **Strava Activities:** Automatic workout journal entries with stats and routes
- **Immich Photos:** Visual storytelling with album integration and photo memories
- **Firefly III Transactions:** Financial reflection and spending pattern insights
- **Google Contacts:** People-focused journaling with relationship tracking
- **Calendar Events:** Event-based journal prompts and reflection

## AI-Powered Features

- **Sentiment Analysis:** Automatic mood detection from journal content
- **Writing Assistance:** AI-powered suggestions and improvements
- **Pattern Recognition:** Insights into mood, activity, and life patterns
- **Reflection Prompts:** Context-aware questions based on recent activities
- **Content Suggestions:** Integration-based writing prompts and ideas
- **Trend Analysis:** Long-term pattern analysis and insights

## Success Criteria

- Rich journaling experience with modern editor and mobile support
- Seamless integration with all external data sources
- AI-powered insights and writing assistance
- Comprehensive search and analytics capabilities
- MCP tools enabling AI assistant collaboration
- Automatic content generation reducing friction for regular journaling
- Export capabilities for data portability

## Next Steps

This iteration enables:
- Calendar integration with event-based journaling (Iteration 5)
- Advanced analytics across all personal data (Iteration 6)
- Long-term pattern recognition and life insights
- AI-powered personal assistant capabilities
