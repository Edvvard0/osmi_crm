"""module 4: appointments, appointment_services

Revision ID: 0004a
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0004a"
down_revision = "0004"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    # btree_gist создан в 0001_extensions.
    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("work_posts.id")),
        sa.Column("department", sa.String(10), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default=sa.text("'scheduled'")),
        sa.Column("comment", sa.String(1000)),
        # FK на work_orders добавит модуль 5.
        sa.Column("work_order_id", sa.Uuid()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("end_at > start_at", name="ck_appointments_period"),
        sa.CheckConstraint(
            "status IN ('scheduled','confirmed','arrived','no_show','cancelled')",
            name="ck_appointments_status",
        ),
        sa.CheckConstraint(
            "department IN ('service','detailing')", name="ck_appointments_department"
        ),
        sa.UniqueConstraint("work_order_id", name="appointments_work_order_id_key"),
    )
    op.execute(
        """
        ALTER TABLE appointments ADD CONSTRAINT appointments_no_overlap
          EXCLUDE USING gist (
            post_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
          ) WHERE (status IN ('scheduled','confirmed','arrived') AND post_id IS NOT NULL)
        """
    )
    op.create_index("ix_appointments_location_start", "appointments", ["location_id", "start_at"])
    op.create_index("ix_appointments_client_id", "appointments", ["client_id"])

    op.create_table(
        "appointment_services",
        sa.Column(
            "appointment_id",
            sa.Uuid(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("service_id", sa.Uuid(), sa.ForeignKey("services.id"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("appointment_services")
    op.drop_table("appointments")
