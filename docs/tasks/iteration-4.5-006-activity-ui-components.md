# Iteration 4.5 Task 006: Activity UI Components (Breakdown)

**Status:** 🟡 IN PROGRESS (PR 1 ✅, PR 2 ✅)
**Goal:** Build UI components for activity display and GPX visualization in manageable, PR-sized increments.
**Parent Task:** [Iteration 4.5: Fitness & Activity Types](./iteration-4.5-fitness-activity-types.md)

This sub-task breaks down ITER4.5-006 into smaller, focused pull requests targeting independent capabilities while adhering to frontend component design patterns (`shadcn/ui`, `TypeEditor` wrappers, form guidelines).
It also shifts GPX track processing to the backend using `gpxpy` and renders on the frontend using `shadcn-map`.

---

## PR 1: Route Domain UI & Selector
**Objective:** Handle the Routes domain first, establishing a pattern for linking a journal to a database route. This lays the groundwork for activities that require a route.

**Tasks:**
- [x] Create `RouteSelector` combo-box component:
  - Fetch existing routes from Backend API `GET /api/routes`.
  - Provide auto-complete/search support to select a `route_id`.
  - Provide a way to link to the route creation flow if a desired route doesn't exist.
- [x] React Testing Library tests for RouteSelector.
- [x] Playwright E2E Test covering the basic route selection behavior.

## PR 2: Backend GPX Processing & API Updates
**Objective:** Implement the backend logic to parse GPX XML and extract map-ready geometries and statistics.

**Tasks:**
- [x] Add `gpxpy` library to `backend/pyproject.toml`.
- [x] Create a GPX utilities module (`backend/app/core/journal/utils/gpx_parser.py`):
  - Parse GPX string using `gpxpy.parse()`.
  - Extract list of coordinates (latitude, longitude) for map polylines.
  - Calculate statistics: distance (2D and 3D), elevation gain/loss, duration.
- [x] Create dedicated GPX endpoint (`GET /api/journals/{id}/gpx`):
  - Serves parsed track points and calculated metrics to the frontend (no raw XML parsing needed client-side).
  - JSON API response with `GPXCoordinateSchema` and `GPXStatisticsSchema`.
- [x] Write pytest unit tests covering the `gpxpy` parsing logic and metric calculations (16 tests).
- [x] Write integration tests for the GPX endpoint (5 tests).

## PR 3: Map Display & Fitness Base UI
**Objective:** Establish the foundation for fitness entries, rendering the map and the base statistics component.

**Tasks:**
- [x] Install `shadcn-map` and `leaflet`/`react-leaflet` in `frontend/`.
- [x] Create `GPXTrackDisplay` component:
  - Use `react-leaflet` (`MapContainer`, `TileLayer`, `Polyline`, `Marker`) to render the GPX track.
  - Render the track using the coordinates array provided by the backend.
  - Add start/end markers (with loop detection to avoid duplicates).
- [x] Create `ActivityStats` component:
  - Design a flexible, reusable component to display metrics in a visually appealing way using `shadcn/ui` Cards or Badges.
  - Base display for fitness metrics (duration, distance, heart rate, elevation, calories).
- [x] Create `FitnessTypeEditor` (`frontend/src/components/journals/type-editors/FitnessTypeEditor.tsx`):
  - Sub-form for heart rate, distance, elevation, duration, and calories.
  - Implement GPX file upload.
- [x] Update `JournalTypeSection.tsx`.
- [x] Unit tests for the UI components.
- [x] E2E Test (Playwright) covering the creation of a `FITNESS` journal entry and map rendering.

## PR 4: Base Outdoor, Jogging & Bushwalking UI
**Objective:** Add UI forms for the remaining common outdoor activities and integrate the route selector.

**Tasks:**
- [x] Create `OutdoorActivityTypeEditor`:
  - Fields for `activity_type`, `weather_conditions`, `role`.
  - Checkboxes for `in_leadership_role` and a text area for `participant_notes`.
- [x] Create `JoggingTypeEditor` (Field for `pace`).
- [x] Create `BushwalkingTypeEditor`:
  - Incorporates the `RouteSelector` from PR 1.
  - Dropdown for the Australian Track Grading System (1-5).
- [x] Extend `ActivityStats` to support displaying specific outdoor parameters (weather, grading, pace).
- [x] React Testing Library tests for editors.
- [x] E2E Tests for `OUTDOOR_ACTIVITY`, `JOGGING`, and `BUSHWALKING`.

## PR 5: Complex Outdoor Activities UI (Abseiling, Canyoning, Climbing, Kayaking, Skiing)
**Objective:** Implement editors for highly specialized activity profiles completing the UI.

**Tasks:**
- [ ] Create `AbseilingTripTypeEditor` (`number_of_abseils`, `total_length`).
- [ ] Create `CanyoningTypeEditor`:
  - `RouteSelector`.
  - Fields for French Grading System (`v`, `a`, `IV` elements).
  - Water gauge fields and flags.
- [ ] Create `ClimbingTypeEditor` (`sport`/`trad`/`bouldering` dropdown, grade, length).
- [ ] Create `KayakingTypeEditor` (`RouteSelector`, `water_type` field).
- [ ] Create `CrossCountrySkiingTypeEditor` (`RouteSelector`, `snow_conditions` area).
- [ ] Update `ActivityStats` plugin formatting for these complex types.
- [ ] React Testing Library tests, including French grade parsing validation.
- [ ] Final visual Polish and E2E Tests.
