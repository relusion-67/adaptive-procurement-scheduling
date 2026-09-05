import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import UserRole

# Deliberately not pydantic's EmailStr: that requires the extra
# `email-validator` dependency for one field. A simple, well-understood
# regex is sufficient here since this is a login identifier, not a field
# we need to send mail to.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Only FARMER accounts may be created through the public, unauthenticated
# registration endpoint. Both CENTRE_STAFF and ADMIN are privileged roles
# that grant access to other people's data (an entire procurement centre's
# operations, or the whole admin surface) and must only ever be created by
# an existing ADMIN via the /admin/users provisioning endpoint below.
# Letting a caller self-select either of those roles here would defeat the
# entire RBAC model, exactly as it did for CENTRE_STAFF prior to this fix.
SELF_REGISTERABLE_ROLES = (UserRole.FARMER,)

# Roles an authenticated ADMIN is allowed to provision via /admin/users.
# ADMIN is included deliberately: this application's intended security
# model permits an existing administrator to create further administrator
# accounts (there is no other in-app path to do so, and the alternative -
# no way to ever add a second admin - is worse from an operational
# security standpoint). This is an explicit design decision, not an
# oversight; if that changes, tighten this tuple rather than the endpoint.
ADMIN_PROVISIONABLE_ROLES = (UserRole.FARMER, UserRole.CENTRE_STAFF, UserRole.ADMIN)


class _RoleResourceMixin(BaseModel):
    """Shared email/role fields for both registration paths.

    Subclasses restrict which roles are acceptable for their entry point;
    the role/resource pairing itself (FARMER needs farmer_id and no
    centre_id, etc.) is enforced later in the service layer, where the
    check can also confirm the referenced farmer/centre actually exists.
    """

    email: str = Field(min_length=3, max_length=255)
    role: UserRole
    farmer_id: int | None = Field(
        default=None, description="Required, and only valid, when role=FARMER."
    )
    centre_id: int | None = Field(
        default=None, description="Required, and only valid, when role=CENTRE_STAFF."
    )

    @field_validator("email")
    @classmethod
    def _email_must_look_like_an_email(cls, value: str) -> str:
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Must be a valid email address")
        return value.lower()


class UserRegister(_RoleResourceMixin):
    """Public, unauthenticated self-registration. FARMER only."""

    password: str = Field(min_length=8, max_length=128)

    @field_validator("role")
    @classmethod
    def _role_must_be_self_registerable(cls, value: UserRole) -> UserRole:
        if value not in SELF_REGISTERABLE_ROLES:
            raise ValueError("This role cannot be self-registered")
        return value


class AdminUserCreate(_RoleResourceMixin):
    """ADMIN-only account provisioning (FARMER, CENTRE_STAFF, or ADMIN).

    Reachable only through POST /api/admin/users, which is protected by
    `require_admin` at the router level - this schema does not itself
    enforce authentication, only that the requested role is one an admin
    is allowed to provision at all.
    """

    password: str = Field(min_length=8, max_length=128)

    @field_validator("role")
    @classmethod
    def _role_must_be_admin_provisionable(cls, value: UserRole) -> UserRole:
        if value not in ADMIN_PROVISIONABLE_ROLES:
            raise ValueError("This role cannot be provisioned")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: UserRole
    farmer_id: int | None
    centre_id: int | None
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
