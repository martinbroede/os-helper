# OpenSearch Helper Tool

A small web tool to define and publish raw JSON events to OpenSearch. It pairs a
Flask backend (using `opensearch-py`) with a dependency-free `<event-editor>`
Web Component.

```
os-helper/
├── backend/
│   ├── app.py                # Flask app + API endpoints
│   ├── opensearch_client.py  # opensearch-py wrapper
│   ├── config.py             # env-based configuration
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── index.html            # demo page with two editors
    └── event-editor.js       # <event-editor> Web Component
```

## Quick start

### 1. OpenSearch

Run a local single-node cluster (security disabled for convenience):

```bash
docker run -d --name opensearch -p 9200:9200 \
  -e "discovery.type=single-node" \
  -e "DISABLE_SECURITY_PLUGIN=true" \
  opensearchproject/opensearch:2
```

### 2. Backend

```bash
python3 -m venv .venv && source .venv/bin/activate
cd backend
pip install -r requirements.txt
cp .env.example .env          # adjust as needed
python app.py
```

The server serves both the API and the frontend at http://127.0.0.1:5000.

### 3. Use it

Open http://127.0.0.1:5000, type a JSON object into an editor, and click
**Push**. Status feedback appears inline, and the activity log records every
push/error via the component's custom events.

## API

### `POST /api/events`

Indexes a single event. Body must be a JSON **object**. Optional
`?index=<name>` query parameter overrides the target index.

```bash
curl -X POST http://127.0.0.1:5000/api/events \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "level": "info"}'
```

Responses:

| Status | Meaning                                            |
| ------ | -------------------------------------------------- |
| 201    | `{"status":"ok","id":...,"index":...,"result":...}`|
| 400    | Empty / invalid JSON, or not a JSON object         |
| 413    | Payload exceeds `MAX_CONTENT_LENGTH`               |
| 502    | OpenSearch rejected the request or is unreachable  |

### `GET /health`

Liveness probe; reports OpenSearch connectivity (`200` up / `503` down).

## The `<event-editor>` component

Vanilla custom element, shadow DOM, no build step. Just include the script:

```html
<script src="event-editor.js" defer></script>
<event-editor endpoint="/api/events" index="events"></event-editor>
```

**Attributes:** `endpoint` (default `/api/events`), `index` (seeds the target-index
input field — the user can edit it before pushing), `placeholder`.

The component renders an **Index** text field; its value at push time determines
the target index (`?index=`). Pushing with an empty index is blocked client-side.

**Events** (bubble + composed):
`event-pushed` → `detail.response`, `event-error` → `detail.message`.

**Slots:** `heading` for a custom title.

**Parts** (for outside styling): `index`, `input`, `button`.

Multiple instances are fully isolated and can coexist on one page.

## Configuration

All settings come from environment variables (see `.env.example`):
`OPENSEARCH_HOST`, `OPENSEARCH_PORT`, `OPENSEARCH_USER`,
`OPENSEARCH_PASSWORD`, `OPENSEARCH_USE_SSL`, `OPENSEARCH_VERIFY_CERTS`,
`OPENSEARCH_INDEX`, `MAX_CONTENT_LENGTH`, `HOST`, `PORT`, `FLASK_DEBUG`.
