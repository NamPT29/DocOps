"""scan packages

Revision ID: 0011_scan_packages
Revises: 0010_case_input_assignment
Create Date: 2026-10-04 22:55:51.678766
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011_scan_packages'
down_revision: Union[str, Sequence[str], None] = '0010_case_input_assignment'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'case_scan_packages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('project_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('scanned_by_name', sa.String(255), nullable=True),
        sa.Column('scanned_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('submitted_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scan_user_name_level', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('source_path', sa.String(1024), nullable=False),
        sa.Column('total_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_a4_equivalent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('conversion_parameters', sa.Text(), nullable=True),
        sa.Column('total_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('warning_flags', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='processing'),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('case_id', 'version', name='uq_case_scan_packages_case_version'),
        sa.CheckConstraint("status IN ('processing', 'done', 'failed')", name='ck_case_scan_packages_status'),
        sa.CheckConstraint('total_pages >= 0', name='ck_case_scan_packages_total_pages'),
        sa.CheckConstraint('total_a4_equivalent >= 0', name='ck_case_scan_packages_total_a4'),
        sa.CheckConstraint('total_files >= 0', name='ck_case_scan_packages_total_files'),
        sa.CheckConstraint('processed_files >= 0', name='ck_case_scan_packages_processed_files'),
        sa.CheckConstraint('failed_files >= 0', name='ck_case_scan_packages_failed_files'),
        info={'revision': '0011_scan_packages'},
    )
    op.create_index('ix_case_scan_packages_case_id', 'case_scan_packages', ['case_id'])
    op.create_index('ix_case_scan_packages_scanned_by_user_id', 'case_scan_packages', ['scanned_by_user_id'])
    op.create_index('ix_case_scan_packages_submitted_by_user_id', 'case_scan_packages', ['submitted_by_user_id'])
    op.create_index('ix_case_scan_packages_status', 'case_scan_packages', ['status'])
    op.create_index(
        'uq_case_scan_packages_active_case', 
        'case_scan_packages', 
        ['case_id'], 
        unique=True,
        sqlite_where=sa.text("status = 'processing'"),
        postgresql_where=sa.text("status = 'processing'")
    )

    op.create_table(
        'case_scan_files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('package_id', sa.Integer(), sa.ForeignKey('case_scan_packages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relative_path', sa.String(1024), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('page_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sha256', sa.String(64), nullable=True),
        sa.Column('a0_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('a1_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('a2_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('a3_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('a4_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('a5_pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('a4_equivalent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_pdf', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('status', sa.String(32), nullable=False, server_default='ok'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ok', 'error', 'incomplete', 'not_pdf')", name='ck_case_scan_files_status'),
        sa.CheckConstraint('page_count >= -1', name='ck_case_scan_files_page_count'),
        sa.CheckConstraint('a0_pages >= 0', name='ck_case_scan_files_a0'),
        sa.CheckConstraint('a1_pages >= 0', name='ck_case_scan_files_a1'),
        sa.CheckConstraint('a2_pages >= 0', name='ck_case_scan_files_a2'),
        sa.CheckConstraint('a3_pages >= 0', name='ck_case_scan_files_a3'),
        sa.CheckConstraint('a4_pages >= 0', name='ck_case_scan_files_a4'),
        sa.CheckConstraint('a5_pages >= 0', name='ck_case_scan_files_a5'),
        sa.CheckConstraint('a4_equivalent >= 0', name='ck_case_scan_files_a4_eq'),
        sa.CheckConstraint('file_size >= 0', name='ck_case_scan_files_size'),
        info={'revision': '0011_scan_packages'},
    )
    op.create_index('ix_case_scan_files_package_id', 'case_scan_files', ['package_id'])
    op.create_index('ix_case_scan_files_package_path', 'case_scan_files', ['package_id', 'relative_path'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_case_scan_files_package_path', table_name='case_scan_files')
    op.drop_index('ix_case_scan_files_package_id', table_name='case_scan_files')
    op.drop_table('case_scan_files')

    op.drop_index('uq_case_scan_packages_active_case', table_name='case_scan_packages')
    op.drop_index('ix_case_scan_packages_status', table_name='case_scan_packages')
    op.drop_index('ix_case_scan_packages_submitted_by_user_id', table_name='case_scan_packages')
    op.drop_index('ix_case_scan_packages_scanned_by_user_id', table_name='case_scan_packages')
    op.drop_index('ix_case_scan_packages_case_id', table_name='case_scan_packages')
    op.drop_table('case_scan_packages')
