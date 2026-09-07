# OpenSearch Helper Tool

A small web tool to define and publish raw JSON events to OpenSearch. It pairs a
Flask backend (using `opensearch-py`) with a dependency-free `<event-editor>`
Web Component.

```
os-helper/
├── backend/
│   ├── app.py                # Flask app + API endpoints
│   ├── opensearch_client.py  # opensearch-py wrapper
│   ├── anomaly_service.py    # Isolation Forest anomaly detection
│   ├── seed_transactions.py  # synthetic transaction seeder
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

| Status | Meaning                                                             |
| ------ | ------------------------------------------------------------------- |
| 201    | `{"status":"ok","id":...,"index":...,"result":...,"anomaly":{...}}` |
| 400    | Empty / invalid JSON, or not a JSON object                          |
| 413    | Payload exceeds `MAX_CONTENT_LENGTH`                                |
| 502    | OpenSearch rejected the request or is unreachable                   |

On success the indexed event is also scored by the anomaly detector and the
verdict is attached under `anomaly` (see below). If the detector cannot run
(e.g. no training data), indexing still succeeds and an `anomaly_error` string
is returned instead.

### `GET /health`

Liveness probe; reports OpenSearch connectivity (`200` up / `503` down).

## Anomaly detection

The backend trains a scikit-learn **Isolation Forest** on financial
transactions stored in OpenSearch and scores incoming events against it. The
model is trained lazily on first use and cached in memory (retrain via the
endpoint below after re-seeding). Scoring uses the numeric features `amount`,
`hour`, and `distance_km`; the categorical `category` — encoded as the index of
its value in the lexically sorted list of categories seen at training time (an
unseen category encodes to `-1`); and one *relation* feature per pair in
`RELATIONS` (default `("amount", "category")`) that measures how far a value sits
from what is typical **within its group** (a robust, group-relative z-score). The
relation is what lets the detector flag *contextual* anomalies — e.g. a tiny
`amount` for a `category` whose amounts are normally large. A data engineer wires
up a new relation by adding an `(value_feature, group_feature)` pair to
`RELATIONS` in `anomaly_service.py`. See `ANOMALY.md` for the math.

### 1. Seed synthetic transactions

Generates a mix of normal and anomalous transactions and bulk-indexes them into
the transactions index (`OPENSEARCH_TRANSACTIONS_INDEX`, default `transactions`):

```bash
cd backend && python seed_transactions.py --count 1000 --recreate
```

The seed is **clean by default** (normal transactions only). Pass
`--with-anomalies` to inject anomalous transactions at `--anomaly-ratio`.

Options: `--count`, `--with-anomalies`, `--anomaly-ratio`, `--index`, `--seed`,
`--recreate`.

### 2. Anomaly result shape

```json
{
  "is_anomaly": true,
  "anomaly_score": 0.154,   // higher = more anomalous (negated decision fn)
  "verdict": "anomalous",
  "features": {"amount": 18000.0, "hour": 3.0, "distance_km": 4200.0, "category": 11.0, "amount_vs_category": 5.7},
  "trained_on": 1000
}
```

### `POST /api/anomaly/analyze`

Score a JSON event **without** indexing it. Same body rules as `/api/events`.
Returns `200 {"status":"ok","anomaly":{...}}`, `400` for bad input, `409` when
the model has no training data, `502` when OpenSearch is unreachable.

### `POST /api/anomaly/retrain`

Force a retrain from current OpenSearch data (call after re-seeding). Returns
`200 {"status":"ok","trained_on":N,"features":[...]}`, `409` when there is no
training data, `502` when OpenSearch is unreachable.

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
`OPENSEARCH_INDEX`, `OPENSEARCH_TRANSACTIONS_INDEX`, `ANOMALY_CONTAMINATION`,
`ANOMALY_TRAINING_SIZE`, `MAX_CONTENT_LENGTH`, `HOST`, `PORT`, `FLASK_DEBUG`.
