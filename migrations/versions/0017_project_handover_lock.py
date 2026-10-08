"""project handover lock

Revision ID: 0017_project_handover_lock
Revises: 0016_case_paper_handoffs
Create Date: 2026-10-08 18:00:00.000000

Khóa sửa hồ sơ sau bàn giao (K1): ba cột mới, có thể trống, trong bảng projects.
SQLite: thêm cột bằng ALTER TABLE ADD COLUMN (kèm REFERENCES), KHÔNG dựng lại bảng projects:
dựng lại bảng khi kết nối đang bật khóa ngoại sẽ xóa dây chuyền dữ liệu của mọi bảng con.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017_project_handover_lock'
down_revision: Union[str, None] = '0016_case_paper_handoffs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = 'fk_projects_handover_locked_by_user_id'
COLUMNS = ('handover_lock_note', 'handover_locked_by_user_id', 'handover_locked_at')


def _is_sqlite() -> bool:
    return op.get_context().dialect.name == 'sqlite'


def upgrade() -> None:
    if _is_sqlite():
        op.execute('ALTER TABLE projects ADD COLUMN handover_locked_at DATETIME')
        op.execute('ALTER TABLE projects ADD COLUMN handover_locked_by_user_id INTEGER REFERENCES users (id)')
        op.execute('ALTER TABLE projects ADD COLUMN handover_lock_note VARCHAR(1000)')
        return
    op.add_column('projects', sa.Column('handover_locked_at', sa.DateTime(), nullable=True))
    op.add_column('projects', sa.Column('handover_locked_by_user_id', sa.Integer(), nullable=True))
    op.add_column('projects', sa.Column('handover_lock_note', sa.String(length=1000), nullable=True))
    op.create_foreign_key(FK_NAME, 'projects', 'users', ['handover_locked_by_user_id'], ['id'])


def downgrade() -> None:
    if _is_sqlite():
        # SQLite không xóa được cột có khóa ngoại: dựng lại bảng (chỉ khi hạ phiên bản).
        with op.batch_alter_table('projects', recreate='always') as batch_op:
            for column in COLUMNS:
                batch_op.drop_column(column)
        return
    op.drop_constraint(FK_NAME, 'projects', type_='foreignkey')
    for column in COLUMNS:
        op.drop_column('projects', column)
