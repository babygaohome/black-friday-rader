"""initial schema (everything as of module N, except offers.next_scan_after: see 0002)

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-27 11:59:08.700089
"""
from alembic import op
import sqlalchemy as sa


revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('products',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('brand', sa.String(length=100), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.Column('category_id', sa.Uuid(), nullable=True),
    sa.Column('gtin', sa.String(length=14), nullable=True),
    sa.Column('ean', sa.String(length=14), nullable=True),
    sa.Column('upc', sa.String(length=14), nullable=True),
    sa.Column('mpn', sa.String(length=100), nullable=True),
    sa.Column('variant_signature', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_products_gtin'), ['gtin'], unique=False)
        batch_op.create_index(batch_op.f('ix_products_mpn'), ['mpn'], unique=False)

    op.create_table('retailers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('domain', sa.String(length=200), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('offers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=True),
    sa.Column('retailer_id', sa.Uuid(), nullable=False),
    sa.Column('retailer_sku', sa.String(length=100), nullable=False),
    sa.Column('url', sa.String(length=2000), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('match_confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('current_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('current_effective_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('original_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('stock_status', sa.Enum('IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK', 'PREORDER', 'BACKORDER', 'UNKNOWN', name='stockstatus'), nullable=False),
    sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['retailer_id'], ['retailers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('retailer_id', 'retailer_sku', name='uq_offer_retailer_sku')
    )
    with op.batch_alter_table('offers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_offers_product_id'), ['product_id'], unique=False)

    op.create_table('product_variants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('colour', sa.String(length=50), nullable=True),
    sa.Column('storage', sa.String(length=50), nullable=True),
    sa.Column('size', sa.String(length=50), nullable=True),
    sa.Column('memory', sa.String(length=50), nullable=True),
    sa.Column('region', sa.String(length=50), nullable=True),
    sa.Column('variant_key', sa.String(length=300), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('variant_key')
    )
    with op.batch_alter_table('product_variants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_product_variants_product_id'), ['product_id'], unique=False)

    op.create_table('retailer_health',
    sa.Column('retailer_id', sa.Uuid(), nullable=False),
    sa.Column('success_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('error_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('captcha_rate', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_success', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['retailer_id'], ['retailers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('retailer_id')
    )
    op.create_table('user_preferences',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('default_alert_channel', sa.String(length=20), nullable=False),
    sa.Column('default_cooldown_minutes', sa.Integer(), nullable=False),
    sa.Column('telegram_chat_id', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('watch_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('target_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('minimum_discount', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('notify_on_stock', sa.Boolean(), nullable=False),
    sa.Column('notify_on_historical_low', sa.Boolean(), nullable=False),
    sa.Column('priority', sa.Enum('LOW', 'NORMAL', 'HIGH', 'CRITICAL', name='priority'), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'product_id', name='uq_watch_user_product')
    )
    with op.batch_alter_table('watch_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_watch_items_product_id'), ['product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_watch_items_user_id'), ['user_id'], unique=False)

    op.create_table('alert_rules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('watch_item_id', sa.Uuid(), nullable=False),
    sa.Column('conditions', sa.JSON(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['watch_item_id'], ['watch_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('alert_rules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alert_rules_watch_item_id'), ['watch_item_id'], unique=False)

    op.create_table('alerts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.Enum('TARGET_PRICE_HIT', 'PRICE_DROP', 'HISTORICAL_LOW', 'RESTOCK', 'LOW_STOCK', 'FLASH_DEAL', name='alerttype'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('watch_item_id', sa.Uuid(), nullable=True),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('offer_id', sa.Uuid(), nullable=False),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('previous_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('deal_score', sa.Integer(), nullable=True),
    sa.Column('read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['watch_item_id'], ['watch_items.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alerts_user_id'), ['user_id'], unique=False)

    op.create_table('match_reviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('offer_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('suggested_product_id', sa.Uuid(), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('method', sa.String(length=30), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'CONFIRMED', 'REJECTED', name='reviewstatus'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['suggested_product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('match_reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_match_reviews_offer_id'), ['offer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_match_reviews_status'), ['status'], unique=False)

    op.create_table('price_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('offer_id', sa.Uuid(), nullable=False),
    sa.Column('price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('effective_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('original_price', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('stock_status', sa.Enum('IN_STOCK', 'LOW_STOCK', 'OUT_OF_STOCK', 'PREORDER', 'BACKORDER', 'UNKNOWN', name='stockstatus'), nullable=False),
    sa.Column('flagged', sa.Boolean(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('price_history', schema=None) as batch_op:
        batch_op.create_index('ix_price_history_offer_ts', ['offer_id', 'timestamp'], unique=False)

    op.create_table('scan_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('offer_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_type', sa.String(length=30), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_scan_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['offer_id'], ['offers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('scan_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scan_jobs_offer_id'), ['offer_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('alert_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'SENT', 'FAILED', 'RETRY', name='notificationstatus'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.String(length=1000), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('notifications')
    with op.batch_alter_table('scan_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_scan_jobs_offer_id'))

    op.drop_table('scan_jobs')
    with op.batch_alter_table('price_history', schema=None) as batch_op:
        batch_op.drop_index('ix_price_history_offer_ts')

    op.drop_table('price_history')
    with op.batch_alter_table('match_reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_match_reviews_status'))
        batch_op.drop_index(batch_op.f('ix_match_reviews_offer_id'))

    op.drop_table('match_reviews')
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_alerts_user_id'))

    op.drop_table('alerts')
    with op.batch_alter_table('alert_rules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_alert_rules_watch_item_id'))

    op.drop_table('alert_rules')
    with op.batch_alter_table('watch_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_watch_items_user_id'))
        batch_op.drop_index(batch_op.f('ix_watch_items_product_id'))

    op.drop_table('watch_items')
    op.drop_table('user_preferences')
    op.drop_table('retailer_health')
    with op.batch_alter_table('product_variants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_product_variants_product_id'))

    op.drop_table('product_variants')
    with op.batch_alter_table('offers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_offers_product_id'))

    op.drop_table('offers')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('retailers')
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_products_mpn'))
        batch_op.drop_index(batch_op.f('ix_products_gtin'))

    op.drop_table('products')
    # PostgreSQL keeps enum types after their tables are gone
    for name in ('notificationstatus', 'reviewstatus', 'alerttype', 'priority', 'stockstatus'):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
