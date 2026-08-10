"""add GitHub connections and repositories

Revision ID: 553a7ddf4183
Revises: 3b52e55b620b
Create Date: 2026-08-10 20:02:08.014450

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.

revision: str = "553a7ddf4183"
down_revision: Union[str, Sequence[str], None] = "3b52e55b620b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "github_connections",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "github_user_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "github_username",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "access_token",
            sa.String(length=512),
            nullable=False,
        ),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_user_id"),
    )

    op.create_index(
        op.f("ix_github_connections_student_id"),
        "github_connections",
        ["student_id"],
        unique=True,
    )

    op.create_table(
        "github_repositories",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "github_repo_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "owner",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "full_name",
            sa.String(length=511),
            nullable=False,
        ),
        sa.Column(
            "default_branch",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_github_repositories_student_id"),
        "github_repositories",
        ["student_id"],
        unique=False,
    )

    # SQLite requires Alembic batch mode when modifying
    # an existing table with a foreign key constraint.
    with op.batch_alter_table(
        "labs",
        schema=None,
    ) as batch_op:

        batch_op.add_column(
            sa.Column(
                "github_repository_id",
                sa.String(length=36),
                nullable=True,
            )
        )

        batch_op.create_index(
            op.f("ix_labs_github_repository_id"),
            ["github_repository_id"],
            unique=False,
        )

        batch_op.create_foreign_key(
            "fk_labs_github_repository_id",
            "github_repositories",
            ["github_repository_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""

    with op.batch_alter_table(
        "labs",
        schema=None,
    ) as batch_op:

        batch_op.drop_constraint(
            "fk_labs_github_repository_id",
            type_="foreignkey",
        )

        batch_op.drop_index(
            op.f("ix_labs_github_repository_id"),
        )

        batch_op.drop_column(
            "github_repository_id",
        )

    op.drop_index(
        op.f("ix_github_repositories_student_id"),
        table_name="github_repositories",
    )

    op.drop_table(
        "github_repositories",
    )

    op.drop_index(
        op.f("ix_github_connections_student_id"),
        table_name="github_connections",
    )

    op.drop_table(
        "github_connections",
    )