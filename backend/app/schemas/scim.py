"""SCIM 2.0 schemas — the documented subset (RFC 7643 / RFC 7644).

SCIM is a wire protocol with a spec, and the parts that matter are the parts
integrators actually depend on: the `schemas` array, `meta.resourceType`,
`ListResponse` envelopes, and the error shape with its `scimType`. Getting
those wrong produces an endpoint that looks SCIM-shaped and fails against
every real client.

Field naming is camelCase because the spec says so, which is why these models
carry explicit aliases rather than following this codebase's usual snake_case
convention. That inconsistency is the protocol's, not ours, and hiding it
would break interoperability.

What is *not* implemented is documented in docs/architecture/scim.md rather
than silently missing: Groups, bulk operations, sorting, ETags, and the
`/Me` endpoint.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


class ScimName(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    given_name: str | None = Field(default=None, alias="givenName")
    family_name: str | None = Field(default=None, alias="familyName")
    formatted: str | None = None


class ScimEmail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    value: str
    # Clients send several addresses and mark one primary. We store one, so
    # the primary flag is how we pick — ignoring it and taking the first
    # would attach a user's alternate address to their account roughly
    # whenever the client's ordering differed from our assumption.
    primary: bool = False
    type: str | None = None


class ScimMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    resource_type: str = Field(default="User", alias="resourceType")
    created: datetime | None = None
    last_modified: datetime | None = Field(default=None, alias="lastModified")
    location: str | None = None


class ScimUserRequest(BaseModel):
    """Inbound user from a SCIM client (Keycloak, Okta, Entra ID)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schemas: list[str] = Field(default_factory=lambda: [USER_SCHEMA])
    # The client's stable identifier for this user in *its* directory. This
    # is what makes provisioning idempotent across a rename: `userName` and
    # email both change, `externalId` does not.
    external_id: str | None = Field(default=None, alias="externalId")
    user_name: str = Field(alias="userName")
    name: ScimName | None = None
    emails: list[ScimEmail] = Field(default_factory=list)
    active: bool = True
    # Not part of core SCIM. Carried as an extension so a client can assign
    # a Meridian role at provisioning time; absent means the default role
    # applies. Documented in scim.md as a deliberate extension rather than
    # left for an integrator to discover.
    roles: list[str] = Field(default_factory=list)

    def primary_email(self) -> str | None:
        """The address to store, or None.

        Falls back to `userName` when no email is supplied, because most
        directories use the address as the username and a user with no
        contactable address is not useful to this platform.
        """
        for email in self.emails:
            if email.primary:
                return email.value
        if self.emails:
            return self.emails[0].value
        return self.user_name if "@" in self.user_name else None


class ScimUserResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schemas: list[str] = Field(default_factory=lambda: [USER_SCHEMA])
    id: uuid.UUID
    external_id: str | None = Field(default=None, alias="externalId")
    user_name: str = Field(alias="userName")
    name: ScimName | None = None
    emails: list[ScimEmail] = Field(default_factory=list)
    active: bool
    roles: list[str] = Field(default_factory=list)
    meta: ScimMeta


class ScimListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schemas: list[str] = Field(default_factory=lambda: [LIST_RESPONSE_SCHEMA])
    total_results: int = Field(alias="totalResults")
    items_per_page: int = Field(alias="itemsPerPage")
    start_index: int = Field(alias="startIndex")
    resources: list[ScimUserResponse] = Field(alias="Resources")


class ScimPatchOperation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Case-insensitive in the spec; clients send both "replace" and
    # "Replace". Normalized in the service rather than rejected, because
    # failing a valid request over letter case is the kind of
    # interoperability bug that takes a day to find.
    op: str
    path: str | None = None
    value: Any = None


class ScimPatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schemas: list[str] = Field(default_factory=lambda: [PATCH_OP_SCHEMA])
    operations: list[ScimPatchOperation] = Field(alias="Operations")


class ScimError(BaseModel):
    """The spec's error envelope.

    `scimType` is what distinguishes machine-actionable failures — a client
    seeing `uniqueness` knows to fetch the existing resource instead of
    retrying the create forever.
    """

    model_config = ConfigDict(populate_by_name=True)

    schemas: list[str] = Field(default_factory=lambda: [ERROR_SCHEMA])
    status: str
    scim_type: (
        Literal[
            "invalidFilter",
            "tooMany",
            "uniqueness",
            "mutability",
            "invalidSyntax",
            "invalidPath",
            "invalidValue",
            "noTarget",
        ]
        | None
    ) = Field(default=None, alias="scimType")
    detail: str | None = None
