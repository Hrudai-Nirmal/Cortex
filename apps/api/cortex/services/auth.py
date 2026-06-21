"""Fixture-compatible OIDC identity resolution and developer RBAC enforcement."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.config import Settings
from cortex.services.audit import persistControlPlaneAudit


@dataclass(frozen=True, slots=True)
class IdentityContext:
    """Carry the authenticated tenant, actor, and group context for one request."""

    enterpriseId: UUID
    actorId: str
    subject: str
    email: str
    displayName: str
    issuer: str
    audience: str
    groups: tuple[str, ...]
    roles: tuple[str, ...]

    @property
    def principalIds(self) -> tuple[str, ...]:
        """Expose identity-derived principals in the same format as retrieval ACL checks."""
        rolePrincipals = tuple(f"role:{role}" for role in self.roles)
        return tuple(dict.fromkeys((*self.groups, *rolePrincipals)))

    @property
    def isAdmin(self) -> bool:
        """Return whether this identity may mutate developer control-plane state."""
        return "admin" in self.roles

    @property
    def isBuilder(self) -> bool:
        """Return whether this identity may access authenticated developer read surfaces."""
        return self.isAdmin or "builder" in self.roles


async def resolveIdentity(
    request: Request,
    settings: Settings,
) -> IdentityContext:
    """Resolve a fixture-compatible OIDC identity from the bearer token."""
    tokenValue = parseBearerToken(request.headers.get("Authorization"))
    claims = buildClaimsFromToken(tokenValue, settings)
    return validateIdentityClaims(claims, settings)


async def requireBuilderIdentity(
    request: Request,
    session: AsyncSession,
    settings: Settings,
    action: str,
    enterpriseId: UUID,
) -> IdentityContext:
    """Require an authenticated builder/admin identity for developer read operations."""
    identity = await resolveIdentity(request, settings)
    if identity.enterpriseId != enterpriseId:
        await recordDeniedAudit(
            session=session,
            settings=settings,
            identity=identity,
            action=action,
            enterpriseId=enterpriseId,
            reason="enterprise-mismatch",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="enterprise mismatch")
    if not identity.isBuilder:
        await recordDeniedAudit(
            session=session,
            settings=settings,
            identity=identity,
            action=action,
            enterpriseId=enterpriseId,
            reason="builder role required",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="builder role required")
    return identity


async def requireAdminIdentity(
    request: Request,
    session: AsyncSession,
    settings: Settings,
    action: str,
    enterpriseId: UUID,
) -> IdentityContext:
    """Require an authenticated admin identity for control-plane mutations."""
    identity = await requireBuilderIdentity(
        request=request,
        session=session,
        settings=settings,
        action=action,
        enterpriseId=enterpriseId,
    )
    if not identity.isAdmin:
        await recordDeniedAudit(
            session=session,
            settings=settings,
            identity=identity,
            action=action,
            enterpriseId=enterpriseId,
            reason="admin role required",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return identity


def parseBearerToken(authorizationHeader: str | None) -> str:
    """Extract a bearer token from the request without silently accepting anonymous access."""
    if authorizationHeader is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    scheme, _, tokenValue = authorizationHeader.partition(" ")
    if scheme.lower() != "bearer" or not tokenValue.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")
    return tokenValue.strip()


def buildClaimsFromToken(tokenValue: str, settings: Settings) -> dict[str, Any]:
    """Resolve fixture aliases or decode a JWT-style payload without signature verification."""
    fixtureClaims = buildFixtureClaims(tokenValue, settings)
    if fixtureClaims is not None:
        return fixtureClaims
    if tokenValue.count(".") == 2:
        _, payloadSegment, _ = tokenValue.split(".", maxsplit=2)
        try:
            decodedPayload = _decodeJwtSegment(payloadSegment)
            claims = json.loads(decodedPayload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token payload could not be decoded",
            ) from error
        if not isinstance(claims, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token payload must be an object",
            )
        return claims
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown fixture token")


def buildFixtureClaims(tokenValue: str, settings: Settings) -> dict[str, Any] | None:
    """Return deterministic local OIDC-like claims for known fixture tokens."""
    fixtureDirectory: dict[str, dict[str, Any]] = {
        "fixture-admin": {
            "aud": settings.oidcAudience,
            "display_name": "Alex Rivera",
            "email": "alex.rivera@example.com",
            "enterprise_id": str(settings.enterpriseId),
            "groups": ["group:employees", "group:platform-admins"],
            "iss": settings.oidcIssuerUrl,
            "roles": ["admin", "builder"],
            "sub": "alex.rivera@example.com",
        },
        "fixture-builder": {
            "aud": settings.oidcAudience,
            "display_name": "Riley Patel",
            "email": "riley.patel@example.com",
            "enterprise_id": str(settings.enterpriseId),
            "groups": ["group:employees", "group:builders"],
            "iss": settings.oidcIssuerUrl,
            "roles": ["builder"],
            "sub": "riley.patel@example.com",
        },
        "fixture-employee": {
            "aud": settings.oidcAudience,
            "display_name": "Maya Chen",
            "email": "maya.chen@example.com",
            "enterprise_id": str(settings.enterpriseId),
            "groups": ["group:employees"],
            "iss": settings.oidcIssuerUrl,
            "roles": ["employee"],
            "sub": "maya.chen@example.com",
        },
    }
    return fixtureDirectory.get(tokenValue)


def validateIdentityClaims(claims: dict[str, Any], settings: Settings) -> IdentityContext:
    """Validate the minimal OIDC claim contract and convert it into Cortex identity context."""
    issuer = str(claims.get("iss", "")).strip()
    audience = claims.get("aud")
    subject = str(claims.get("sub", "")).strip()
    email = str(claims.get("email", subject)).strip()
    enterpriseId = str(claims.get("enterprise_id", "")).strip()
    if issuer != settings.oidcIssuerUrl:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="issuer mismatch")
    if audience != settings.oidcAudience:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="audience mismatch")
    if not subject or not email or not enterpriseId:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token is missing required identity claims",
        )
    groups = tuple(
        dict.fromkeys(
            str(group).strip() for group in claims.get("groups", []) if str(group).strip()
        )
    )
    roles = tuple(
        dict.fromkeys(str(role).strip() for role in claims.get("roles", []) if str(role).strip())
    )
    if not roles:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token has no roles")
    return IdentityContext(
        enterpriseId=UUID(enterpriseId),
        actorId=email,
        subject=subject,
        email=email,
        displayName=str(claims.get("display_name", email)).strip() or email,
        issuer=issuer,
        audience=audience,
        groups=groups,
        roles=roles,
    )


async def recordDeniedAudit(
    session: AsyncSession,
    settings: Settings,
    identity: IdentityContext,
    action: str,
    enterpriseId: UUID,
    reason: str,
) -> None:
    """Persist denied developer access so permission enforcement is independently auditable."""
    await persistControlPlaneAudit(
        session=session,
        settings=settings,
        enterpriseId=enterpriseId,
        actorId=identity.actorId,
        action=action,
        scope={
            "enterpriseId": str(enterpriseId),
            "principalIds": list(identity.principalIds),
            "required": "admin-or-builder",
        },
        outcome="denied",
        eventPayload={"reason": reason},
    )


def _decodeJwtSegment(payloadSegment: str) -> bytes:
    """Decode one base64url JWT segment while tolerating omitted padding."""
    paddingLength = (-len(payloadSegment)) % 4
    paddedSegment = payloadSegment + ("=" * paddingLength)
    return base64.urlsafe_b64decode(paddedSegment.encode("ascii"))
