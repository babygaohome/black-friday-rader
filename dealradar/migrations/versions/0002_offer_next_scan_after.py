"""offers.next_scan_after: failure backoff / dispatch claim for the scan dispatcher

Revision ID: 0002_offer_next_scan_after
Revises: 0001_initial
Create Date: 2026-10-27 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002_offer_next_scan_after'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('offers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_scan_after', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('offers', schema=None) as batch_op:
        batch_op.drop_column('next_scan_after')
