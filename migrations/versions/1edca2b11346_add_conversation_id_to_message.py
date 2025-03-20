"""Add conversation_id to Message

Revision ID: 1edca2b11346
Revises: 0035a381a617
Create Date: 2025-03-20 15:19:26.295095

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1edca2b11346'
down_revision = '0035a381a617'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('message', schema=None) as batch_op:
        batch_op.add_column(sa.Column('conversation_id', sa.String(length=100), nullable=False, server_default='temp'))  # 临时默认值

def downgrade():
    with op.batch_alter_table('message', schema=None) as batch_op:
        batch_op.drop_column('conversation_id')

    # ### end Alembic commands ###
