"""Application configuration loaded from environment variables.

Values are read once at import time. A local ``.env`` file (if present) is
loaded first so that development overrides do not need to be exported into the
shell manually.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Interpret a string environment value as a boolean.

    Args:
        value: The raw environment value, or ``None`` when unset.
        default: Value returned when ``value`` is ``None`` or empty.

    Returns:
        The parsed boolean.
    """
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the OpenSearch helper service."""

    # OpenSearch connection.
    opensearch_host: str = os.getenv("OPENSEARCH_HOST", "localhost")
    opensearch_port: int = int(os.getenv("OPENSEARCH_PORT", "9200"))
    opensearch_user: str | None = os.getenv("OPENSEARCH_USER") or None
    opensearch_password: str | None = os.getenv("OPENSEARCH_PASSWORD") or None
    opensearch_use_ssl: bool = _as_bool(os.getenv("OPENSEARCH_USE_SSL"), False)
    opensearch_verify_certs: bool = _as_bool(
        os.getenv("OPENSEARCH_VERIFY_CERTS"), False
    )

    # Default index events are written to when the request does not specify one.
    default_index: str = os.getenv("OPENSEARCH_INDEX", "events")

    # Index holding the financial transactions the anomaly detector trains on.
    transactions_index: str = os.getenv("OPENSEARCH_TRANSACTIONS_INDEX", "transactions")

    # Expected fraction of anomalies in the training data. Passed to the
    # Isolation Forest as its ``contamination`` parameter.
    anomaly_contamination: float = float(os.getenv("ANOMALY_CONTAMINATION", "0.05"))

    # Maximum number of transactions pulled from OpenSearch to train the model.
    anomaly_training_size: int = int(os.getenv("ANOMALY_TRAINING_SIZE", "10000"))

    # Maximum accepted request body size in bytes (default 1 MiB).
    max_content_length: int = int(os.getenv("MAX_CONTENT_LENGTH", str(1024 * 1024)))

    # Flask server.
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "5000"))
    debug: bool = _as_bool(os.getenv("FLASK_DEBUG"), False)


config = Config()
