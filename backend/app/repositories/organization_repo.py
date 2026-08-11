from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ExternalEntityType, OrganizationStatus, ProviderType
from app.models.organization import ExternalIdentity, Organization


def get_by_id(db: Session, organization_id: UUID) -> Organization | None:
    return db.get(Organization, organization_id)


def get_by_slug(db: Session, slug: str) -> Organization | None:
    return db.scalars(select(Organization).where(Organization.slug == slug)).first()


def get_by_external_id(
    db: Session, *, system: ProviderType, external_id: str
) -> Organization | None:
    """Resolve an organization through its identity in an external system.

    The join every inbound sync starts from: "I have Salesforce Account
    001xx…, which organization is that?" Going through external_identities
    rather than a column on organizations is what lets Keycloak, SCIM and
    Graph answer the same question in Phases 3-5 without a schema change.
    """
    identity = db.scalars(
        select(ExternalIdentity).where(
            ExternalIdentity.system == system,
            ExternalIdentity.entity_type == ExternalEntityType.ORGANIZATION,
            ExternalIdentity.external_id == external_id,
        )
    ).first()
    if identity is None:
        return None
    return db.get(Organization, identity.entity_id)


def list_all(db: Session) -> list[Organization]:
    return list(db.scalars(select(Organization).order_by(Organization.name)))


def create_with_external_identity(
    db: Session,
    *,
    name: str,
    slug: str,
    system: ProviderType,
    external_id: str,
    status: OrganizationStatus = OrganizationStatus.PROSPECTIVE,
    primary_domain: str | None = None,
    external_url: str | None = None,
    connection_id: UUID | None = None,
) -> Organization:
    """Create an organization and its external mapping in one transaction.

    One commit, not two. An organization without its mapping is invisible to
    the next sync, which would then create a second organization for the
    same Salesforce account — the exact duplication the mapping table exists
    to prevent. They are one fact and must land together.
    """
    organization = Organization(
        name=name,
        slug=_unique_slug(db, slug),
        status=status,
        primary_domain=primary_domain,
    )
    db.add(organization)
    # Flush rather than commit: assigns the primary key so the identity row
    # can reference it, while leaving both inserts in the same transaction.
    db.flush()

    db.add(
        ExternalIdentity(
            system=system,
            entity_type=ExternalEntityType.ORGANIZATION,
            entity_id=organization.id,
            external_id=external_id,
            external_url=external_url,
            connection_id=connection_id,
        )
    )
    db.commit()
    db.refresh(organization)
    return organization


def _unique_slug(db: Session, base: str) -> str:
    """Append a counter until the slug is free.

    Two genuinely different customers can share a name closely enough to
    slugify identically ("Cordant Industries" and "Cordant, Industries!").
    The slug is unique in the database, so without this the second one's
    insert fails — a real customer's onboarding blocked by a punctuation
    coincidence.
    """
    if get_by_slug(db, base) is None:
        return base
    for suffix in range(2, 100):
        candidate = f"{base[:95]}-{suffix}"
        if get_by_slug(db, candidate) is None:
            return candidate
    raise ValueError(f"Could not derive a unique slug from '{base}'")


def create(db: Session, **fields: Any) -> Organization:
    organization = Organization(**fields)
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


def link_external_identity(
    db: Session,
    *,
    entity_id: UUID,
    entity_type: ExternalEntityType,
    system: ProviderType,
    external_id: str,
    external_url: str | None = None,
    connection_id: UUID | None = None,
) -> ExternalIdentity:
    identity = ExternalIdentity(
        system=system,
        entity_type=entity_type,
        entity_id=entity_id,
        external_id=external_id,
        external_url=external_url,
        connection_id=connection_id,
    )
    db.add(identity)
    db.commit()
    db.refresh(identity)
    return identity
