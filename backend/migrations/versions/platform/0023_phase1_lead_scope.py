"""Grant the LeadIntake service identity the dedicated ``write:lead`` scope."""

import hashlib
import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0023_phase1_lead_scope"
down_revision: str | None = "0022_phase1_lead_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_DEV_API_KEY = "edp-dev-agent-hub-key"


def _key_hash() -> str:
    raw_key = os.environ.get("EDP_DEV_API_KEY") or DEFAULT_DEV_API_KEY
    return hashlib.sha256(raw_key.encode()).hexdigest()


def upgrade() -> None:
    """Add only the lead-ingestion scope to the configured service identity."""
    op.get_bind().execute(
        text(
            """
            UPDATE platform.api_keys
            SET scopes = scopes || ARRAY['write:lead']
            WHERE key_hash = :key_hash
              AND NOT ('write:lead' = ANY(scopes))
            """
        ),
        {"key_hash": _key_hash()},
    )


def downgrade() -> None:
    """Remove only the scope introduced by this migration."""
    op.get_bind().execute(
        text(
            """
            UPDATE platform.api_keys
            SET scopes = array_remove(scopes, 'write:lead')
            WHERE key_hash = :key_hash
              AND 'write:lead' = ANY(scopes)
            """
        ),
        {"key_hash": _key_hash()},
    )
