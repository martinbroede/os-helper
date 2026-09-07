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

from anomaly_service import (
    FEATURES,
    AnomalyModelNotReady,
    analyze_event,
    train_model,
    training_count,
)
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

    # Run the freshly-indexed event through the anomaly recognition service.
    # A failure here (e.g. model not yet trained) must not fail event creation,
    # so it is reported alongside the successful indexing result.
    anomaly: dict[str, object] | None = None
    anomaly_error: str | None = None
    try:
        anomaly = analyze_event(document)
    except AnomalyModelNotReady as exc:
        anomaly_error = str(exc)
        logger.warning("Anomaly analysis skipped: %s", exc)
    except OpenSearchException as exc:
        anomaly_error = f"OpenSearch error during analysis: {exc}"
        logger.exception("Anomaly analysis failed")

    body: dict[str, object] = {
        "status": "ok",
        "id": result.get("_id"),
        "index": result.get("_index"),
        "result": result.get("result"),
    }
    if anomaly is not None:
        body["anomaly"] = anomaly
    if anomaly_error is not None:
        body["anomaly_error"] = anomaly_error

    return jsonify(body), 201


@app.post("/api/anomaly/analyze")
def analyze() -> object:
    """Score a JSON event for anomalies *without* indexing it.

    The request body must be a JSON object. Returns the anomaly analysis (see
    :func:`anomaly_service.analyze_event`).

    Returns:
        ``200`` with the analysis, ``400`` for malformed input, ``409`` when the
        detector has no training data, ``502`` when OpenSearch is unreachable.
    """
    raw = request.get_data(as_text=True)
    if not raw or not raw.strip():
        return jsonify({"status": "error", "message": "Request body is empty."}), 400
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        return (
            jsonify({"status": "error", "message": f"Invalid JSON: {exc.msg}."}),
            400,
        )
    if not isinstance(document, dict) or not document:
        return (
            jsonify(
                {"status": "error", "message": "Event must be a non-empty JSON object."}
            ),
            400,
        )

    try:
        anomaly = analyze_event(document)
    except AnomalyModelNotReady as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
    except OpenSearchException as exc:
        logger.exception("Anomaly analysis failed")
        return jsonify({"status": "error", "message": f"OpenSearch error: {exc}"}), 502

    return jsonify({"status": "ok", "anomaly": anomaly}), 200


@app.post("/api/anomaly/retrain")
def retrain() -> object:
    """Force a retrain of the Isolation Forest from current OpenSearch data.

    Call this after (re)seeding the transactions index so the model reflects the
    new data.

    Returns:
        ``200`` with the number of transactions trained on, ``409`` when there
        is no training data, ``502`` when OpenSearch is unreachable.
    """
    try:
        train_model(force=True)
    except AnomalyModelNotReady as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
    except OpenSearchException as exc:
        logger.exception("Model retraining failed")
        return jsonify({"status": "error", "message": f"OpenSearch error: {exc}"}), 502

    return (
        jsonify(
            {
                "status": "ok",
                "trained_on": training_count(),
                "features": list(FEATURES),
            }
        ),
        200,
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
