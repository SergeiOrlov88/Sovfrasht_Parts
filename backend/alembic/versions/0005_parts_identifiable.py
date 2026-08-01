"""parts: soft identifiability invariant

Revision ID: 0005_parts_identifiable
Revises: 0004_parts_without_codes
Create Date: 2026-08-01 11:47:24.453661
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005_parts_identifiable'
down_revision: Union[str, None] = '0004_parts_without_codes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Мягкий инвариант вместо снятого «минимум один код»: у позиции есть
    название И хотя бы производитель или применимое оборудование. Совсем
    неопознаваемых строк в каталоге быть не должно (docs/07 §3)."""
    condition = "name IS NOT NULL AND (maker IS NOT NULL OR equipment IS NOT NULL)"
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # NOT VALID: существующие строки не перепроверяем, но новые уже под контролем
        op.execute(f"ALTER TABLE parts ADD CONSTRAINT ck_parts_identifiable CHECK ({condition})")
    else:
        with op.batch_alter_table("parts", recreate="always") as batch:
            batch.create_check_constraint("ck_parts_identifiable", condition)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE parts DROP CONSTRAINT IF EXISTS ck_parts_identifiable")
    else:
        with op.batch_alter_table("parts", recreate="always") as batch:
            batch.drop_constraint("ck_parts_identifiable", type_="check")
