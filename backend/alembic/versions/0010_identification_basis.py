# -*- coding: utf-8 -*-
"""Основание опознания: by_number | appearance (FR-REC-07).

Аддитивная и nullable колонка: у результатов, обработанных до введения
признака, основание неизвестно, и это честнее, чем задним числом объявить
их опознанными по номеру.

Revision ID: 0010_identification_basis
Revises: 0009_notifications
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0010_identification_basis'
down_revision: Union[str, None] = '0009_notifications'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recognitions',
        sa.Column('identification_basis', sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('recognitions', 'identification_basis')
