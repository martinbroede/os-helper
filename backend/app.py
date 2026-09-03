"""Flask application exposing the OpenSearch event-push API.

Endpoints:
    ``GET  /``            Serve the demo page hosting ``<event-editor>``.
    ``GET  /health``      Liveness / OpenSearch connectivity probe.
    ``POST /api/events``  Validate a JSON event and index it into OpenSearch.

The frontend (static Web Component) is served from the sibling ``frontend``
directory so the whole tool runs from a single process.
"""

from __future__ import annotations

import datetime
import json
import logging
import os

from config import config
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from opensearch_client import ping, push_event
from opensearchpy.exceptions import OpenSearchException

logging.basicConfig(
    level=logging.DEBUG if config.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("os_helper")

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = config.max_content_length
CORS(app)


@app.get("/")
def index() -> object:
    """Serve the demo HTML page."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename: str) -> object:
    """Serve static frontend assets (JS/CSS)."""
    return send_from_directory(FRONTEND_DIR, filename)


@app.get("/health")
def health() -> object:
    """Report service liveness and OpenSearch connectivity."""
    reachable = ping()
    status_code = 200 if reachable else 503
    return (
        jsonify({"status": "ok", "opensearch": "up" if reachable else "down"}),
        status_code,
    )


@app.post("/api/events")
def create_event() -> object:
    """Validate a raw JSON event and index it into OpenSearch.

    The request body must be a JSON *object* (an event document). An optional
    ``?index=<name>`` query parameter overrides the target index.

    Returns:
        A JSON response describing the result. ``201`` on success, ``400`` for
        malformed input, ``502`` when OpenSearch rejects or cannot serve the
        request.
    """
    raw = request.get_data(as_text=True)
    if not raw or not raw.strip():
        return jsonify({"status": "error", "message": "Request body is empty."}), 400

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Invalid JSON: {exc.msg} (line {exc.lineno}, "
                    f"column {exc.colno}).",
                }
            ),
            400,
        )

    if not isinstance(document, dict):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Event must be a JSON object, got "
                    f"{type(document).__name__}.",
                }
            ),
            400,
        )

    if not document:
        return (
            jsonify({"status": "error", "message": "Event object is empty."}),
            400,
        )

    index = request.args.get("index") or None

    try:
        document["@timestamp"] = (
            document.get("@timestamp")
            or datetime.datetime.now(tz=datetime.timezone.utc).isoformat() + "Z"
        )
        result = push_event(document, index=index)
    except OpenSearchException as exc:
        logger.exception("Failed to push event to OpenSearch")
        try:
            detail = str(exc) or exc.__class__.__name__
        except Exception:  # noqa: BLE001 - some OS exceptions raise on str()
            detail = exc.__class__.__name__
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"OpenSearch error: {detail}",
                }
            ),
            502,
        )

    return (
        jsonify(
            {
                "status": "ok",
                "id": result.get("_id"),
                "index": result.get("_index"),
                "result": result.get("result"),
            }
        ),
        201,
    )


@app.errorhandler(413)
def payload_too_large(_error: object) -> object:
    """Return a JSON error when the request body exceeds the size limit."""
    return (
        jsonify(
            {
                "status": "error",
                "message": "Payload too large.",
            }
        ),
        413,
    )


if __name__ == "__main__":
    app.run(host=config.host, port=config.port, debug=config.debug)
