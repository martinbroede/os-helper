# OpenSearch Helper Tool

## Overview
Build a web-based event editor and push service for OpenSearch. Users can define and publish events to OpenSearch via a reusable UI component.

## Scope

### Backend (Python/Flask)
- HTTP endpoint to receive JSON events
- Push events to OpenSearch cluster using opensearch-py client
- Event validation/logging

### Frontend
- Web Component: `<event-editor>`
  - Text input field for JSON document
  - Push button to submit event
  - Support multiple instances per page
  - Error/success feedback (via slot or event)
  - Encapsulated styling (shadow DOM)
  - No external dependencies

## User Flow
1. User inputs JSON event in editor component
2. User clicks "Push" button
3. Event JSON sent to backend via HTTP POST
4. Backend pushes event to OpenSearch
5. UI updates with result status

## Acceptance Criteria
- [ ] Backend endpoint accepts and validates JSON events
- [ ] OpenSearch client successfully publishes events
- [ ] Frontend component is reusable and self-contained
- [ ] Multiple editors can coexist on same page without conflicts
- [ ] Clear feedback on success/failure to user

## Technical Notes
- Stack: Python/Flask + Web Components (vanilla JS/HTML/CSS)
- OpenSearch client: opensearch-py
- Event format: Raw JSON document strings
- Frontend: No build tooling required, custom element API
