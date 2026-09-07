# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A single-process web tool to define and publish raw JSON events to OpenSearch. A
Flask backend (`opensearch-py`) serves both the JSON API and a dependency-free
`<event-editor>` Web Component from the sibling `frontend/` directory. Indexed
events are additionally scored for anomalies by a scikit-learn **Isolation
Forest** trained on synthetic financial transactions stored in OpenSearch.

## Commands

```bash
# One-time setup (from repo root)
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env      # adjust as needed

# Run (serves API + frontend at http://127.0.0.1:5000)
cd backend && python app.py

# Seed synthetic financial transactions the anomaly detector trains on
cd backend && python seed_transactions.py --count 1000 --recreate

# Local OpenSearch for development (security disabled)
docker run -d --name opensearch -p 9200:9200 \
  -e "discovery.type=single-node" -e "DISABLE_SECURITY_PLUGIN=true" \
  opensearchproject/opensearch:2
```

There is no test suite, linter config, or build step in this repo. The frontend
is vanilla JS with no bundler — edits to `frontend/*` are live on reload.

## Architecture

Three-layer backend, all config-driven via environment variables:

- `backend/config.py` — a frozen `Config` dataclass read **once at import time**
  (`.env` loaded via `python-dotenv`). Everything downstream imports the
  `config` singleton. Changing config requires a process restart.
- `backend/opensearch_client.py` — thin wrapper over `opensearch-py`. The client
  is a **lazy singleton** (`get_client`): the Flask app starts and serves the
  frontend even when OpenSearch is down; connection errors only surface on an
  actual `push_event`/`ping`. Also exposes `bulk_index` (used by the seeder) and
  `fetch_all` (a `match_all` read used by the anomaly trainer; returns `[]` for a
  missing index).
- `backend/anomaly_service.py` — Isolation Forest anomaly detection. The model is
  a **lazy, cached singleton** (`train_model`) fit on transactions read from the
  transactions index; scoring uses only the numeric features in `FEATURES`
  (`amount`, `hour`, `distance_km`). `analyze_event` returns
  `{is_anomaly, anomaly_score, verdict, features, trained_on}` where
  `anomaly_score` is the **negated** decision function (higher = more anomalous).
  Raises `AnomalyModelNotReady` when the transactions index is empty. Retraining
  requires `force=True` (the cached model is not auto-refreshed).
- `backend/seed_transactions.py` — CLI that generates synthetic transactions and
  bulk-indexes them into the transactions index. **Clean by default** (normal
  transactions only, so the seed is an unpoisoned baseline); pass
  `--with-anomalies` to inject clearly-anomalous ones at `--anomaly-ratio`
  (default `config.anomaly_contamination`). Reproducible via `--seed`;
  `--recreate` drops the index first.
- `backend/app.py` — Flask routes. `POST /api/events` validates that the body is
  a non-empty JSON **object**, injects an `@timestamp` if absent, and indexes
  with `refresh=True`; on success it also scores the event and attaches the
  result under `anomaly` (a detector failure never fails indexing — it surfaces
  as `anomaly_error` with a still-`201` response). `POST /api/anomaly/analyze`
  scores an event **without** indexing it; `POST /api/anomaly/retrain` forces a
  retrain from current data. `GET /health` reports OpenSearch reachability.
  `GET /` and `GET /<path>` serve static files from `../frontend`. Errors map to
  specific status codes: 400 (bad/empty/non-object JSON), 409 (detector has no
  training data), 413 (over `MAX_CONTENT_LENGTH`), 502 (`OpenSearchException`).

Frontend `frontend/event-editor.js` — a single `EventEditor` custom element using
shadow DOM (fully style/DOM isolated, so multiple instances coexist). Key
contract used by the backend/demo page:

- Attributes: `endpoint` (default `/api/events`), `index` (seeds the editable
  index field), `placeholder`. The **index value at push time** becomes the
  `?index=` query param; empty index is blocked client-side.
- Emits bubbling + composed events: `event-pushed` (`detail.response`) and
  `event-error` (`detail.message`).
- Exposes CSS `part`s: `index`, `input`, `button`; and a `heading` slot.

The API/component contract is documented in detail in `README.md` — keep it in
sync when changing endpoints, attributes, events, or parts.
