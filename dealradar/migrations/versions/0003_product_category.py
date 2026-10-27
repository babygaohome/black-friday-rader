"""products.category: keyword-based category slug, backfilled for existing products

Revision ID: 0003_product_category
Revises: 0002_offer_next_scan_after
Create Date: 2026-10-27 21:00:00
"""
from alembic import op
import sqlalchemy as sa

from dealradar.normalization.category import classify

revision = '0003_product_category'
down_revision = '0002_offer_next_scan_after'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=40), nullable=True))
        batch_op.create_index(batch_op.f('ix_products_category'), ['category'], unique=False)
    conn = op.get_bind()
    products = sa.table('products', sa.column('id', sa.Uuid), sa.column('name', sa.String), sa.column('brand', sa.String),
                        sa.column('category', sa.String))
    for pid, name, brand in conn.execute(sa.select(products.c.id, products.c.name, products.c.brand)).all():
        conn.execute(products.update().where(products.c.id == pid).values(category=classify(name or "", brand or "")))


def downgrade() -> None:
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_products_category'))
        batch_op.drop_column('category')
