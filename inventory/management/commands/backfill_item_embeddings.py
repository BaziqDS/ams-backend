"""
Backfill the hybrid copilot search indexes for existing Items.

Use cases:
  - First-time rollout after enabling ITEM_SEARCH_HYBRID_ENABLED.
  - Retry items whose previous embed call failed (empty hash).
  - Recompute everything after switching embedding models.

The command is idempotent: it skips items whose stored embedded_text_hash
already matches the current text. Pass --force to re-embed unconditionally
(needed when changing models, since old vectors and new vectors are not
comparable across models).

Examples:
  python manage.py backfill_item_embeddings
  python manage.py backfill_item_embeddings --batch-size 50
  python manage.py backfill_item_embeddings --dry-run
  python manage.py backfill_item_embeddings --force
  python manage.py backfill_item_embeddings --only-missing
"""

from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from inventory.models.item_model import Item
from inventory.services.embeddings import (
    build_item_embedding_text,
    embed_item,
    hash_text,
)
from inventory.signals import _has_embedding, _refresh_tsvector, _write_embedding

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill embeddings and tsvectors for all non-provisional Items."

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Items per fetch batch (default 100).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be embedded, do not write or call the API.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-embed even items whose hash already matches.',
        )
        parser.add_argument(
            '--only-missing',
            action='store_true',
            help='Skip items that already have a non-null embedding.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Process at most N items (0 = no limit).',
        )

    def handle(self, *args, **opts):
        if connection.vendor != 'postgresql':
            raise CommandError(
                "Hybrid search is Postgres-only. Active DB vendor is "
                f"{connection.vendor!r}."
            )
        if not getattr(settings, 'ITEM_SEARCH_HYBRID_ENABLED', False):
            self.stdout.write(self.style.WARNING(
                "ITEM_SEARCH_HYBRID_ENABLED is False — proceeding anyway "
                "since you ran this command explicitly. Remember to flip the "
                "flag on after the backfill completes."
            ))

        batch_size = opts['batch_size']
        dry_run = opts['dry_run']
        force = opts['force']
        only_missing = opts['only_missing']
        limit = opts['limit']

        queryset = (
            Item.objects
            .filter(is_provisional=False)
            .select_related('category__parent_category')
            .order_by('id')
        )
        if only_missing:
            # `embedding` isn't a Django ORM field — filter via raw SQL.
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT id FROM inventory_item "
                    "WHERE is_provisional = FALSE AND embedding IS NULL"
                )
                missing_ids = [row[0] for row in cur.fetchall()]
            queryset = queryset.filter(pk__in=missing_ids)

        total = queryset.count()
        if limit:
            total = min(total, limit)
        self.stdout.write(self.style.NOTICE(
            f"Backfilling {total} item(s) "
            f"(batch_size={batch_size}, force={force}, dry_run={dry_run})"
        ))

        processed = 0
        embedded = 0
        skipped = 0
        failed = 0
        start = time.time()

        offset = 0
        while True:
            chunk = list(queryset[offset:offset + batch_size])
            if not chunk:
                break

            for item in chunk:
                if limit and processed >= limit:
                    break
                processed += 1

                text = build_item_embedding_text(item)
                desired_hash = hash_text(text)

                if (not force
                        and item.embedded_text_hash == desired_hash
                        and _has_embedding(item.pk)):
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f"  [dry-run] would embed item {item.id} "
                        f"({item.name!r}, {len(text)} chars)"
                    )
                    continue

                result = embed_item(item)
                Item.objects.filter(pk=item.pk).update(
                    embedded_text_hash=result.text_hash,
                )
                if result.vector is None:
                    failed += 1
                else:
                    _write_embedding(item.pk, result.vector)
                    embedded += 1
                _refresh_tsvector(item.pk)

            if limit and processed >= limit:
                break
            offset += batch_size

        elapsed = time.time() - start
        self.stdout.write(self.style.SUCCESS(
            f"Done. processed={processed} embedded={embedded} "
            f"skipped={skipped} failed={failed} elapsed={elapsed:.1f}s"
        ))
