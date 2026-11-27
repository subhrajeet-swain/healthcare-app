from dataclasses import dataclass
from typing import Literal
from uuid import UUID

Role = Literal["patient", "lab_staff", "doctor", "lab_admin", "platform_admin"]


@dataclass(frozen=True)
class TenantCtx:
    """Who the request is for. Worked out once, from the login route or the session cookie."""

    tenant_id: UUID
    user_id: UUID | None = None
    role: Role | None = None
    # Set when the signed-in user (actor_id) acts for a family member (user_id), via X-Profile.
    actor_id: UUID | None = None
