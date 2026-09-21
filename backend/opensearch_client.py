"""Thin wrapper around the ``opensearch-py`` client.

The client is created lazily so the Flask app can start (and serve the
frontend) even when OpenSearch is temporarily unreachable. Connection errors
surface only when an event is actually pushed.
"""

from __future__ import annotations

import logging
from typing import Any

from config import config
from opensearchpy import OpenSearch
from opensearchpy.exceptions import OpenSearchException

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


def clear_index(index: str) -> dict[str, Any]:
    """Delete every document from an index, keeping the index itself.

    Args:
        index: Name of the index to empty.

    Returns:
        The raw ``delete_by_query`` response body (contains ``deleted``,
        ``total``, ``failures``, etc.).

    Raises:
        NotFoundError: If the index does not exist.
        OpenSearchException: If OpenSearch rejects the request or is
            unreachable.
    """
    client = get_client()
    response = client.delete_by_query(
        index=index,
        body={"query": {"match_all": {}}},
        refresh=True,
    )
    logger.info(
        "Cleared index '%s' (deleted=%s, failures=%s)",
        index,
        response.get("deleted"),
        len(response.get("failures") or []),
    )
    return response
