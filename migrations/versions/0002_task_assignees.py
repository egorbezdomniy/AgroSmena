"""Store task assignees and the cached organization member list."""
from alembic import op
import sqlalchemy as sa

revision = '0002_task_assignees'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tasks') as batch:
        batch.add_column(sa.Column('assignee_usernames', sa.Text(), nullable=False, server_default='[]'))
    with op.batch_alter_table('saved_sync_login') as batch:
        batch.add_column(sa.Column('members_json', sa.Text(), nullable=False, server_default='[]'))


def downgrade():
    raise RuntimeError('Task assignment downgrade is destructive. Restore a backup instead.')
