"""Seed OpenSearch with synthetic financial transactions.

Generates synthetic transactions and bulk-indexes them into the transactions
index that ``anomaly_service`` trains on. By default the seed is **clean**
(normal transactions only), so it serves as an unpoisoned baseline: contextual
detectors that learn per-group statistics (see ``RELATIONS`` in
``anomaly_service``) are not skewed by outliers mixed into the training data.

Pass ``--with-anomalies`` to inject clearly-anomalous transactions, crafted to
stand out on the numeric features the detector uses (large amounts, odd hours,
far-flung locations).

Usage::

    cd backend && python seed_transactions.py [--count N]         # clean seed
    python seed_transactions.py --with-anomalies [--anomaly-ratio R]
    python seed_transactions.py --recreate      # drop the index first
"""

from __future__ import annotations

import argparse
import datetime
import logging
import random
import sys

from config import config
from opensearch_client import bulk_index, get_client
from opensearchpy.exceptions import OpenSearchException

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_transactions")

# Each category maps to a plausible ``(min, max)`` euro amount range. The spread
# is deliberately wide across categories so that ``amount`` carries a real signal
# — a €5 wage or a €9000 grocery run is unusual regardless of the other features.
CATEGORY_AMOUNT_RANGES: dict[str, tuple[float, float]] = {
    "groceries": (5.0, 250.0),
    "restaurant": (10.0, 200.0),
    "fuel": (20.0, 150.0),
    "transport": (2.0, 120.0),
    "subscription": (5.0, 60.0),
    "utilities": (30.0, 400.0),
    "insurance": (20.0, 600.0),
    "healthcare": (15.0, 800.0),
    "electronics": (50.0, 3000.0),
    "rent": (400.0, 2500.0),
    "travel": (100.0, 5000.0),
    "wages": (2500.0, 10000.0),
}

CATEGORIES = tuple(CATEGORY_AMOUNT_RANGES)


def _timestamp(rng: random.Random) -> str:
    """Return an ISO-8601 timestamp within the last 30 days.

    Args:
        rng: Seeded random generator for reproducibility.

    Returns:
        An ISO-8601 UTC timestamp string.
    """
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    offset = datetime.timedelta(
        days=rng.randint(0, 29),
        hours=rng.randint(0, 23),
        minutes=rng.randint(0, 59),
    )
    return (now - offset).isoformat()


def make_normal(rng: random.Random) -> dict[str, object]:
    """Build a single plausible, everyday transaction.

    Args:
        rng: Seeded random generator.

    Returns:
        A transaction document.
    """
    category = rng.choice(CATEGORIES)
    low, high = CATEGORY_AMOUNT_RANGES[category]
    return {
        "amount": round(rng.uniform(low, high), 2),
        "hour": rng.randint(7, 21),
        "distance_km": round(rng.uniform(0.0, 30.0), 1),
        "category": category,
        "@timestamp": _timestamp(rng),
    }


def make_anomaly(rng: random.Random) -> dict[str, object]:
    """Build a single clearly-anomalous transaction.

    Anomalies combine at least one extreme feature: an amount far outside the
    normal range for its category, an unusual hour (small hours of the night),
    and/or an implausible distance from the account's usual location.

    Args:
        rng: Seeded random generator.

    Returns:
        A clearly-anomalous transaction document.
    """
    category = rng.choice(CATEGORIES)
    high = CATEGORY_AMOUNT_RANGES[category][1]
    return {
        # Well above what this category ever costs (5-10x its usual ceiling).
        "amount": round(high * rng.uniform(5.0, 10.0), 2),
        "hour": rng.choice([0, 1, 2, 3, 4]),
        "distance_km": round(rng.uniform(500.0, 8000.0), 1),
        "category": category,
        "@timestamp": _timestamp(rng),
    }


def generate(count: int, anomaly_ratio: float, seed: int) -> list[dict[str, object]]:
    """Generate a shuffled dataset of normal and anomalous transactions.

    Args:
        count: Total number of transactions to generate.
        anomaly_ratio: Fraction (0-1) of transactions that are anomalous.
        seed: Random seed for reproducibility.

    Returns:
        The generated transaction documents.
    """
    rng = random.Random(seed)
    num_anomalies = round(count * anomaly_ratio)
    documents = [make_anomaly(rng) for _ in range(num_anomalies)]
    documents += [make_normal(rng) for _ in range(count - num_anomalies)]
    rng.shuffle(documents)
    return documents


def recreate_index(index: str) -> None:
    """Delete the transactions index if it exists (ignores 404).

    Args:
        index: The index name to drop.
    """
    client = get_client()
    client.indices.delete(index=index, ignore=[404])
    logger.info("Dropped index '%s'", index)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, generate the dataset, and index it.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        A process exit code (``0`` on success, ``1`` on OpenSearch failure).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count", type=int, default=1000, help="Total transactions to generate."
    )
    parser.add_argument(
        "--with-anomalies",
        action="store_true",
        help="Inject anomalous transactions. Off by default so the seed stays a "
        "clean baseline; enable it to build a deliberately poisoned dataset.",
    )
    parser.add_argument(
        "--anomaly-ratio",
        type=float,
        default=config.anomaly_contamination,
        help="Fraction of anomalous transactions (only applied with "
        "--with-anomalies).",
    )
    parser.add_argument(
        "--index",
        default=config.transactions_index,
        help="Target index (default from config).",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--recreate", action="store_true", help="Drop the index before seeding."
    )
    args = parser.parse_args(argv)

    anomaly_ratio = args.anomaly_ratio if args.with_anomalies else 0.0
    documents = generate(args.count, anomaly_ratio, args.seed)
    num_anomalies = round(args.count * anomaly_ratio)
    logger.info(
        "Generated %s transactions (%s anomalous) for index '%s'",
        len(documents),
        num_anomalies,
        args.index,
    )

    try:
        if args.recreate:
            recreate_index(args.index)
        succeeded, failed = bulk_index(documents, index=args.index)
    except OpenSearchException as exc:
        logger.error("Failed to seed OpenSearch: %s", exc)
        return 1

    logger.info("Indexed %s transactions (%s failed).", succeeded, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
