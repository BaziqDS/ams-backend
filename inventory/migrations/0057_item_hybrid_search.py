"""
Hybrid copilot item search — schema additions.

Adds (both Postgres and SQLite):
  - search_text          (tsvector on Postgres, text on SQLite — unused there)
  - embedded_text_hash   (varchar)

Adds (Postgres only, via vendor-gated RunPython):
  - CREATE EXTENSION vector
  - ALTER TABLE inventory_item ADD COLUMN embedding vector(N)
  - GIN index on search_text
  - HNSW index on embedding

The embedding column is intentionally NOT declared as a Django ORM field —
that would force every INSERT to bind it and break on SQLite where the
column does not exist. The signal and backfill command write to it via raw
SQL after gating on connection.vendor.
"""

from django.conf import settings
from django.db import migrations, models
from django.contrib.postgres.search import SearchVectorField


def _create_postgres_objects(apps, schema_editor):
    """Create pgvector extension, embedding column, and Postgres-only indexes."""
    if schema_editor.connection.vendor != 'postgresql':
        return

    dim = int(getattr(settings, 'EMBEDDING_DIM', 1536))
    with schema_editor.connection.cursor() as cursor:
        # Extension first — required for the vector type to resolve.
        cursor.execute('CREATE EXTENSION IF NOT EXISTS vector')

        # Embedding column — skip if it somehow already exists.
        cursor.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'inventory_item' AND column_name = 'embedding'
        """)
        exists = cursor.fetchone() is not None
        if not exists:
            cursor.execute(
                f'ALTER TABLE inventory_item ADD COLUMN embedding vector({dim})'
            )

        # GIN index on the tsvector column for BM25-style lookups.
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS item_search_text_gin
              ON inventory_item USING gin (search_text)
        """)

        # HNSW index on the embedding column for ANN cosine search.
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS item_embedding_hnsw
              ON inventory_item USING hnsw (embedding vector_cosine_ops)
              WITH (m = 16, ef_construction = 64)
        """)


def _drop_postgres_objects(apps, schema_editor):
    """Reverse — drop indexes and the embedding column. Leave the extension alone."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS item_embedding_hnsw')
        cursor.execute('DROP INDEX IF EXISTS item_search_text_gin')
        cursor.execute('ALTER TABLE inventory_item DROP COLUMN IF EXISTS embedding')


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0056_alter_location_options'),
    ]

    operations = [
        # These two field adds work on both Postgres and SQLite.
        # SearchVectorField degrades to a text column on SQLite — harmless.
        migrations.AddField(
            model_name='item',
            name='search_text',
            field=SearchVectorField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='item',
            name='embedded_text_hash',
            field=models.CharField(max_length=64, blank=True, default=''),
        ),

        # All Postgres-only DDL (extension, embedding column, indexes).
        migrations.RunPython(
            _create_postgres_objects,
            _drop_postgres_objects,
            elidable=False,
        ),
    ]
