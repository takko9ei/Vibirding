"""Add the species catalog and optional observation species reference.

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "species",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_chinese_name", sa.Text(), nullable=False),
        sa.Column("scientific_name", sa.Text(), nullable=True),
        sa.Column("taxonomy_source", sa.Text(), nullable=False),
        sa.Column("taxonomy_key", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_species"),
        sa.UniqueConstraint(
            "taxonomy_source", "taxonomy_key", name="uq_species_source_key"
        ),
    )
    op.add_column(
        "observations",
        sa.Column("species_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_observations_species_id_species",
        "observations",
        "species",
        ["species_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_observations_species_id_species", "observations", type_="foreignkey"
    )
    op.drop_column("observations", "species_id")
    op.drop_table("species")
