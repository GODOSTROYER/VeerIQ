"""Static local demo identities (the UI labels these "Local demo identities")."""

from __future__ import annotations

from rewindsafe.contracts import Identity

IDENTITIES: dict[str, Identity] = {
    i.identity_id: i
    for i in (
        Identity(
            identity_id="maya",
            name="Nova",
            email="nova.reyes@atlas.example",
            role="operator",
            tenant_id="atlas",
            title="Incident commander \u00b7 Atlas Outfitters",
            initials="NO",
            color="#8B7CF6",
        ),
        Identity(
            identity_id="dev",
            name="Orion",
            email="orion.vance@atlas.example",
            role="reviewer",
            tenant_id="atlas",
            title="Finance controller \u00b7 second reviewer",
            initials="OR",
            color="#34D399",
        ),
        Identity(
            identity_id="sam",
            name="Lyra",
            email="lyra.okafor@beacon.example",
            role="operator",
            tenant_id="beacon",
            title="Ops lead \u00b7 Beacon Coffee Co.",
            initials="LY",
            color="#F59E0B",
        ),
    )
}


def get_identity(identity_id: str) -> Identity | None:
    return IDENTITIES.get(identity_id)
