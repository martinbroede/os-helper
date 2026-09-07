"""Thin wrapper around the ``opensearch-py`` client.

The client is created lazily so the Flask app can start (and serve the
frontend) even when OpenSearch is temporarily unreachable. Connection errors
surface only when an event is actually pushed.
"""

from __future__ import annotations

import logging
from typing import Any

from config import config
from opensearchpy import OpenSearch, helpers
from opensearchpy.exceptions import NotFoundError, OpenSearchException

logger = logging.getLogger(__name__)

_client: OpenSearch | None = None


def get_client() -> OpenSearch:
    """Return a singleton OpenSearch client, creating it on first use.

    Returns:
        The configured :class:`OpenSearch` client.
    """
    global _client
    if _client is None:
        auth = None
        if config.opensearch_user and config.opensearch_password:
            auth = (config.opensearch_user, config.opensearch_password)

        _client = OpenSearch(
            hosts=[{"host": config.opensearch_host, "port": config.opensearch_port}],
            http_auth=auth,
            use_ssl=config.opensearch_use_ssl,
            verify_certs=config.opensearch_verify_certs,
            ssl_show_warn=False,
        )
        logger.info(
            "Created OpenSearch client for %s:%s (ssl=%s)",
            config.opensearch_host,
            config.opensearch_port,
            config.opensearch_use_ssl,
        )
    return _client


def push_event(document: dict[str, Any], index: str | None = None) -> dict[str, Any]:
    """Index a single event document into OpenSearch.

    Args:
        document: The parsed JSON event to index.
        index: Target index name; falls back to the configured default.

    Returns:
        The raw response body returned by OpenSearch (contains the generated
        document ``_id``, ``result``, etc.).

    Raises:
        OpenSearchException: If OpenSearch rejects the request or is
            unreachable.
    """
    target_index = index or config.default_index
    client = get_client()
    response = client.index(index=target_index, body=document, refresh=True)
    logger.info(
        "Indexed event into '%s' as id=%s (result=%s)",
        target_index,
        response.get("_id"),
        response.get("result"),
    )
    return response


def bulk_index(
    documents: list[dict[str, Any]], index: str | None = None
) -> tuple[int, int]:
    """Index many documents in a single bulk request.

    Args:
        documents: The document bodies to index.
        index: Target index name; falls back to the configured default.

    Returns:
        A ``(succeeded, failed)`` tuple counting the indexed documents.

    Raises:
        OpenSearchException: If OpenSearch is unreachable or rejects the bulk
            request outright.
    """
    target_index = index or config.default_index
    client = get_client()
    actions = ({"_index": target_index, "_source": doc} for doc in documents)
    succeeded, errors = helpers.bulk(client, actions, refresh=True, stats_only=False)
    failed = len(errors) if isinstance(errors, list) else int(errors)
    logger.info(
        "Bulk-indexed %s document(s) into '%s' (%s failed)",
        succeeded,
        target_index,
        failed,
    )
    return succeeded, failed


def fetch_all(
    index: str | None = None, batch_size: int = 10000
) -> list[dict[str, Any]]:
    """Retrieve *every* document from an index via a ``match_all`` query.

    Uses a scroll (``helpers.scan``) so the result is not capped at the
    ``index.max_result_window`` limit (10,000 by default) that bounds a single
    ``search`` request.

    Args:
        index: Index to read from; falls back to the configured default.
        batch_size: Number of documents fetched per scroll request. This only
            controls request chunking; all matching documents are returned.

    Returns:
        A list of the raw ``_source`` bodies. An empty list is returned when the
        index does not exist yet.

    Raises:
        OpenSearchException: If OpenSearch is unreachable or the search fails
            for a reason other than a missing index.
    """
    target_index = index or config.default_index
    client = get_client()
    try:
        hits = helpers.scan(
            client,
            index=target_index,
            query={"query": {"match_all": {}}},
            size=batch_size,
        )
        return [hit["_source"] for hit in hits]
    except NotFoundError:
        logger.warning("Index '%s' does not exist yet", target_index)
        return []


def ping() -> bool:
    """Check whether the OpenSearch cluster is reachable.

    Returns:
        ``True`` if the cluster responds to a ping, ``False`` otherwise.
    """
    try:
        return bool(get_client().ping())
    except OpenSearchException as exc:  # pragma: no cover - network dependent
        logger.warning("OpenSearch ping failed: %s", exc)
        return False
