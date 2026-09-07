"""Isolation-Forest-based anomaly recognition for financial transactions.

The service trains a :class:`sklearn.ensemble.IsolationForest` on the
transactions stored in OpenSearch (see ``seed_transactions.py``) and scores
individual events against it. Training is *lazy* and *cached*: the model is
fitted on first use and reused for subsequent scoring until an explicit
retrain is requested. This mirrors the lazy-singleton style of
``opensearch_client.get_client``.

Feature vector
--------------
Each transaction is reduced to a small numeric feature vector, in three parts:

1. The numeric fields in :data:`FEATURES`, taken as-is.
2. The categorical fields in :data:`CATEGORICAL_FEATURES`, each encoded as the
   index it would occupy in the lexically sorted list of distinct values seen at
   training time (an unseen value encodes to ``-1``). This *vocabulary* is built
   once during training and cached alongside the model.
3. One derived feature per *relation* in :data:`RELATIONS`. A relation connects a
   numeric feature to a grouping feature and emits a **robust, group-relative
   deviation**: how many (MAD-scaled) units the numeric value sits from the
   median of its group. This is what lets the otherwise axis-independent
   Isolation Forest catch *contextual* anomalies — e.g. a tiny ``amount`` for a
   ``category`` whose amounts are normally large — that are unremarkable on every
   raw axis. Per-group baselines are computed with the **median/MAD** (not
   mean/std) so a few outliers in the training data cannot skew them; they are
   built once during training and cached alongside the model.

Only these fields participate in scoring; any other fields on an event are
ignored, and missing numeric features default to ``0.0``.
"""

from __future__ import annotations

import logging
import statistics
import threading
from typing import Any

from config import config
from opensearch_client import fetch_all
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

#: Numeric features extracted from a transaction, in a fixed order. The order is
#: part of the contract: it must be identical for training and scoring.
FEATURES: tuple[str, ...] = ("amount", "hour", "distance_km")

#: Categorical (string) features, appended to the vector after the numeric ones.
#: Each is encoded to the index of its value in the lexically sorted vocabulary
#: built at training time (see :func:`_build_vocabularies`).
CATEGORICAL_FEATURES: tuple[str, ...] = ("category",)

#: Feature *relations*: each ``(value_feature, group_feature)`` pair emits one
#: derived feature — the group-relative deviation of ``value_feature`` within the
#: buckets of ``group_feature`` (see :func:`_build_relation_stats`). This is the
#: generic hook for a data engineer to "connect" two features so the detector can
#: flag contextual anomalies. Add a pair here to wire up a new relation.
RELATIONS: tuple[tuple[str, str], ...] = (("amount", "category"),)

#: Derived feature names, one per relation, used in the response ``features`` map.
RELATION_FEATURES: tuple[str, ...] = tuple(
    f"{value}_vs_{group}" for value, group in RELATIONS
)

#: Full feature order (numeric, then categorical, then relation deviations). The
#: order is part of the contract: identical for training and scoring.
ALL_FEATURES: tuple[str, ...] = FEATURES + CATEGORICAL_FEATURES + RELATION_FEATURES

#: Index used for a categorical value not present in the training vocabulary.
UNKNOWN_CATEGORY_INDEX: int = -1

#: Consistency constant scaling the MAD to a standard-deviation estimate under a
#: normal distribution, so relation deviations read on a familiar z-score scale.
MAD_TO_STD: float = 1.4826

#: Type alias for a relation's cached baselines: per-group ``(center, scale)``
#: plus a ``"global"`` fallback used for groups unseen at training time.
RelationStats = dict[str, Any]

_model: IsolationForest | None = None
_training_count: int = 0
#: Per-feature ``{value: sorted_index}`` maps, rebuilt on every (re)train.
_vocabularies: dict[str, dict[str, int]] = {}
#: Per-relation baselines keyed by ``(value_feature, group_feature)``.
_relation_stats: dict[tuple[str, str], RelationStats] = {}
_lock = threading.Lock()


class AnomalyModelNotReady(RuntimeError):
    """Raised when scoring is requested but the model cannot be trained.

    This typically means the transactions index is empty — run
    ``seed_transactions.py`` first.
    """


def _coerce_float(value: Any) -> float | None:
    """Coerce a value to ``float``, or ``None`` if it is missing/non-numeric.

    Args:
        value: Any document field value.

    Returns:
        The value as a ``float``, or ``None`` when it cannot be coerced.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _center_scale(values: list[float]) -> tuple[float, float]:
    """Compute a robust center and spread for a group of values.

    Uses the **median** as center and the **median absolute deviation** (scaled
    by :data:`MAD_TO_STD`) as spread. Both are resistant to outliers, so a few
    anomalies mixed into the training data cannot skew a group's baseline. A
    degenerate (zero) spread falls back to ``1.0`` to keep the deviation finite.

    Args:
        values: The numeric values observed for one group.

    Returns:
        A ``(center, scale)`` pair with ``scale > 0``.
    """
    center = statistics.median(values)
    mad = statistics.median([abs(value - center) for value in values])
    scale = MAD_TO_STD * mad
    return center, scale if scale > 0 else 1.0


def _build_relation_stats(
    transactions: list[dict[str, Any]],
) -> dict[tuple[str, str], RelationStats]:
    """Compute per-group baselines for every relation in :data:`RELATIONS`.

    For each ``(value_feature, group_feature)`` relation, the values of
    ``value_feature`` are bucketed by ``group_feature`` and reduced to a robust
    ``(center, scale)`` per group (see :func:`_center_scale`). A ``"global"``
    baseline over all values is also kept, used at scoring time for groups not
    seen during training.

    Args:
        transactions: The training documents.

    Returns:
        A mapping from each relation to ``{"groups": {group: (center, scale)},
        "global": (center, scale)}``.
    """
    stats: dict[tuple[str, str], RelationStats] = {}
    for value_feature, group_feature in RELATIONS:
        by_group: dict[str, list[float]] = {}
        all_values: list[float] = []
        for tx in transactions:
            value = _coerce_float(tx.get(value_feature))
            group = tx.get(group_feature)
            if value is None or group is None:
                continue
            by_group.setdefault(str(group), []).append(value)
            all_values.append(value)
        stats[(value_feature, group_feature)] = {
            "groups": {
                group: _center_scale(values) for group, values in by_group.items()
            },
            "global": _center_scale(all_values) if all_values else (0.0, 1.0),
        }
    return stats


def _build_vocabularies(
    transactions: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Build ``{value: sorted_index}`` maps for the categorical features.

    For each field in :data:`CATEGORICAL_FEATURES`, the distinct values present
    in the training set are sorted lexically and assigned their positional index
    — that index is the value the feature contributes to the vector.

    Args:
        transactions: The training documents.

    Returns:
        A mapping from each categorical feature name to its
        ``{value: sorted_index}`` vocabulary.
    """
    vocabularies: dict[str, dict[str, int]] = {}
    for feature in CATEGORICAL_FEATURES:
        values = {
            str(tx[feature])
            for tx in transactions
            if tx.get(feature) is not None
        }
        vocabularies[feature] = {
            value: index for index, value in enumerate(sorted(values))
        }
    return vocabularies


def _vectorize(
    document: dict[str, Any],
    vocabularies: dict[str, dict[str, int]],
    relation_stats: dict[tuple[str, str], RelationStats],
) -> list[float]:
    """Reduce a transaction document to its numeric feature vector.

    The vector concatenates, in :data:`ALL_FEATURES` order: the raw numeric
    features, the vocabulary-encoded categorical features, and one group-relative
    deviation per relation.

    Args:
        document: A transaction (or event) body.
        vocabularies: The per-feature ``{value: sorted_index}`` maps built at
            training time.
        relation_stats: The per-relation baselines built at training time.

    Returns:
        The feature vector. Missing/non-numeric numeric values become ``0.0``,
        unseen categorical values become :data:`UNKNOWN_CATEGORY_INDEX`, and a
        relation whose value or stats are unavailable contributes ``0.0`` (a
        neutral, on-baseline deviation).
    """
    vector: list[float] = []
    for feature in FEATURES:
        value = _coerce_float(document.get(feature))
        vector.append(value if value is not None else 0.0)
    for feature in CATEGORICAL_FEATURES:
        vocab = vocabularies.get(feature, {})
        raw = document.get(feature)
        index = vocab.get(str(raw), UNKNOWN_CATEGORY_INDEX) if raw is not None \
            else UNKNOWN_CATEGORY_INDEX
        vector.append(float(index))
    for value_feature, group_feature in RELATIONS:
        stats = relation_stats.get((value_feature, group_feature))
        value = _coerce_float(document.get(value_feature))
        if stats is None or value is None:
            vector.append(0.0)
            continue
        group = document.get(group_feature)
        center, scale = stats["groups"].get(str(group), stats["global"])
        vector.append((value - center) / scale)
    return vector


def train_model(force: bool = False) -> IsolationForest:
    """Fit (or return the cached) Isolation Forest on OpenSearch transactions.

    Args:
        force: When ``True``, retrain even if a cached model exists (e.g. after
            seeding new data).

    Returns:
        The fitted :class:`IsolationForest`.

    Raises:
        AnomalyModelNotReady: If the transactions index holds no documents.
        opensearchpy.exceptions.OpenSearchException: If OpenSearch is
            unreachable.
    """
    global _model, _training_count, _vocabularies, _relation_stats
    with _lock:
        if _model is not None and not force:
            return _model

        transactions = fetch_all(
            index=config.transactions_index, batch_size=config.anomaly_training_size
        )
        if not transactions:
            raise AnomalyModelNotReady(
                "No transactions available to train the anomaly detector. "
                "Seed the index first (python seed_transactions.py)."
            )

        vocabularies = _build_vocabularies(transactions)
        relation_stats = _build_relation_stats(transactions)
        samples = [
            _vectorize(tx, vocabularies, relation_stats) for tx in transactions
        ]
        model = IsolationForest(
            n_estimators=200,
            contamination=config.anomaly_contamination,
            random_state=42,
        )
        model.fit(samples)

        _model = model
        _training_count = len(samples)
        _vocabularies = vocabularies
        _relation_stats = relation_stats
        logger.info(
            "Trained Isolation Forest on %s transaction(s) (features=%s)",
            _training_count,
            ALL_FEATURES,
        )
        return _model


def training_count() -> int:
    """Return the number of transactions the current model was fit on.

    Returns:
        The sample count, or ``0`` if no model has been trained yet.
    """
    return _training_count


def analyze_event(document: dict[str, Any]) -> dict[str, Any]:
    """Score a single event and classify it as normal or anomalous.

    The model is trained lazily on first call. The returned ``anomaly_score`` is
    oriented so that **higher means more anomalous** (it is the negated
    Isolation Forest decision function); values above ``0`` correspond to the
    model's anomaly verdict.

    Args:
        document: The event body to score. Only the fields referenced by
            :data:`ALL_FEATURES` (numeric, categorical, and relation inputs) are
            used.

    Returns:
        A dict with:
            ``is_anomaly`` (bool): The model's verdict.
            ``anomaly_score`` (float): Higher = more anomalous.
            ``verdict`` (str): ``"anomalous"`` or ``"normal"``.
            ``features`` (dict): The scored vector keyed by :data:`ALL_FEATURES`
                (includes each relation's group-relative deviation).
            ``trained_on`` (int): Number of transactions the model was fit on.

    Raises:
        AnomalyModelNotReady: If the model cannot be trained (no data).
        opensearchpy.exceptions.OpenSearchException: If OpenSearch is
            unreachable during training.
    """
    model = train_model()
    vector = _vectorize(document, _vocabularies, _relation_stats)
    # decision_function: negative for anomalies, positive for inliers. Negate so
    # that a larger score consistently means "more anomalous".
    anomaly_score = float(-model.decision_function([vector])[0])
    is_anomaly = int(model.predict([vector])[0]) == -1
    return {
        "is_anomaly": is_anomaly,
        "anomaly_score": round(anomaly_score, 6),
        "verdict": "anomalous" if is_anomaly else "normal",
        "features": dict(zip(ALL_FEATURES, vector)),
        "trained_on": _training_count,
    }
