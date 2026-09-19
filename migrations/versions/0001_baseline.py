"""Frozen baseline of the desktop v0.1 + synchronization schema."""
from alembic import op
import sqlalchemy as sa

revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('uuid', sa.String(36), nullable=False),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())]


def text(name, size=None, nullable=False):
    return sa.Column(name, sa.String(size) if size else sa.Text, nullable=nullable)


def upgrade():
    metadata = sa.MetaData()
    customers = sa.Table('customers', metadata, *record_columns(), text('name', 200), text('company_name', 200),
        text('phone', 50), text('email', 200), text('telegram', 100), text('position', 150), text('notes'))
    deals = sa.Table('deals', metadata, *record_columns(), text('title', 250),
        sa.Column('customer_id', sa.Integer, sa.ForeignKey('customers.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False), text('stage', 50), text('description'),
        sa.Column('expected_close_date', sa.Date), sa.CheckConstraint('amount >= 0', name='ck_deals_amount_nonnegative'))
    tasks = sa.Table('tasks', metadata, *record_columns(), text('title', 250), text('description'),
        sa.Column('customer_id', sa.Integer, sa.ForeignKey('customers.id', ondelete='SET NULL')),
        sa.Column('deal_id', sa.Integer, sa.ForeignKey('deals.id', ondelete='SET NULL')),
        sa.Column('due_date', sa.Date), text('priority', 30), text('status', 30))
    sa.Table('sync_state', metadata, sa.Column('id', sa.Integer, primary_key=True), text('server_url', 500),
        text('organization_uuid', 36), text('organization_name', 200), sa.Column('last_sync_at', sa.DateTime))
    sa.Table('sync_deletions', metadata, sa.Column('entity', sa.String(20), primary_key=True),
        sa.Column('uuid', sa.String(36), primary_key=True), sa.Column('updated_at', sa.DateTime, nullable=False))
    sa.Table('saved_sync_login', metadata, sa.Column('id', sa.Integer, primary_key=True), text('server_url', 500),
        text('organization_uuid', 36), text('organization_name', 200), text('username', 150), text('protected_token', 8192))
    for table, fields in [(customers, ['name']), (deals, ['title', 'customer_id', 'stage']),
                          (tasks, ['title', 'customer_id', 'deal_id', 'due_date', 'priority', 'status'])]:
        sa.Index(f'ix_{table.name}_uuid', table.c.uuid, unique=True)
        for name in fields:
            sa.Index(f'ix_{table.name}_{name}', table.c[name])
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in metadata.sorted_tables:
        if inspector.has_table(table.name):
            actual = {column['name'] for column in inspector.get_columns(table.name)}
            if not set(table.columns.keys()).issubset(actual):
                raise RuntimeError(f'Unsupported existing SQLite schema: {table.name}')
        else:
            table.create(bind)


def downgrade():
    raise RuntimeError('Baseline downgrade is destructive. Restore the pre-update SQLite backup instead.')
