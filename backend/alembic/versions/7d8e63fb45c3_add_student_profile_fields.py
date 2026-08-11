"""add student profile fields

Revision ID: 7d8e63fb45c3
Revises: 3e58a6eb699a
Create Date: 2026-08-11 17:15:41.952370

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.

revision: str = "7d8e63fb45c3"
down_revision: Union[str, Sequence[str], None] = "3e58a6eb699a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Add profile fields.
    op.add_column(
        "students",
        sa.Column(
            "name",
            sa.String(length=100),
            nullable=True,
        ),
    )

    op.add_column(
        "students",
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=True,
        ),
    )

    # Add updated_at as nullable first because the students table
    # already contains existing rows.
    op.add_column(
        "students",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Give existing students an initial updated_at value.
    op.execute(
        sa.text(
            "UPDATE students "
            "SET updated_at = CURRENT_TIMESTAMP "
            "WHERE updated_at IS NULL"
        )
    )

    # Now that every existing row has a value, make the column required.
    with op.batch_alter_table("students") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""

    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("email")
        batch_op.drop_column("name")