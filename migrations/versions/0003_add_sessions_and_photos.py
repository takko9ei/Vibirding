"""Add confirmed sessions, photo metadata, and batch relationships.

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
    )
    op.add_column(
        "observations",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_observations_session_id_sessions",
        "observations",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("species_label", sa.Text(), nullable=True),
        sa.Column("scientific_name", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider_candidate_id", sa.Text(), nullable=True),
        sa.Column("species_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["species_id"], ["species.id"],
            name="fk_photos_species_id_species", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"],
            name="fk_photos_session_id_sessions", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["observations.id"],
            name="fk_photos_observation_id_observations", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_photos"),
        sa.UniqueConstraint("content_hash", name="uq_photos_content_hash"),
    )


def downgrade() -> None:
    op.drop_table("photos")
    op.drop_constraint(
        "fk_observations_session_id_sessions", "observations", type_="foreignkey"
    )
    op.drop_column("observations", "session_id")
    op.drop_table("sessions")
