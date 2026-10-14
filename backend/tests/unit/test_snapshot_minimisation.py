"""Snapshot minimisation: the agent-facing inspect_snapshot result never carries a customer's full address.

The helper tests are pure. The end-to-end test calls ``ADAPTER.execute`` the way test_w2_workflow.py does and
uses the ``fresh`` fixture from conftest.py, so it runs against the disposable test database only.
"""

from __future__ import annotations

import json

import pytest

from rewindsafe.contracts import ActionProposal, DispatchStatus
from rewindsafe.runtime import db
from rewindsafe.runtime.canonical import utcnow
from rewindsafe.runtime.identities import IDENTITIES
from rewindsafe.workflows.rewindsafe import ADAPTER, tools
from rewindsafe.workflows.rewindsafe import adapter as wf_adapter
from rewindsafe.workflows.rewindsafe import fixture as fx
from rewindsafe.workflows.rewindsafe import queries as q
from rewindsafe.workflows.rewindsafe import scenarios as sc

MAYA = IDENTITIES["maya"]
RUN = "run_minimisation_test"


@pytest.mark.parametrize(
    ("address", "masked"),
    [
        ("ap@northwind.example", "a***@northwind.example"),
        ("j@juniper.example", "***@juniper.example"),
        ("billing", "***"),
        (None, None),
    ],
)
def test_mask_email_hides_local_part_and_keeps_domain(address, masked):
    assert wf_adapter.mask_email(address) == masked


def test_access_grant_keeps_service_account_and_masks_person_principal():
    service = {"grant_id": "AG-12", "principal": "svc-fulfillment"}
    person = {"grant_id": "AG-99", "principal": "dana@atlas.example"}
    assert wf_adapter._agent_access_grant(service) == service
    assert wf_adapter._agent_access_grant(person) == {"grant_id": "AG-99", "principal": "d***@atlas.example"}


def test_inspect_result_hides_customer_addresses_and_keeps_grants(fresh):
    from rewindsafe.runtime.adapter import ToolContext

    scenario = sc.scenario_by_id("poisoned")
    grant = ADAPTER.build_grant(scenario, MAYA, fresh)
    args = {"snapshot_id": fx.SNAPSHOT_ID, "tenant_id": "atlas"}
    ctx = ToolContext(
        run_id=RUN,
        proposal=ActionProposal(
            proposal_id="prop_inspect_minimisation", run_id=RUN, step_index=0, tool=tools.INSPECT_SNAPSHOT,
            arguments=args, created_at=utcnow(),
        ),
        grant=grant, identity=MAYA, scenario=scenario, enforcement_mode="offline",
    )

    outcome = ADAPTER.execute(ctx, tools.INSPECT_SNAPSHOT, args)
    assert outcome.status is DispatchStatus.EXECUTED
    observation = outcome.observation
    text = json.dumps(observation)

    # No full customer address reaches the agent, in any part of the result.
    for customer in fx.SNAPSHOT_CUSTOMERS:
        assert customer["email"] not in text

    # The rows the agent needs stay recognisable: name and domain are kept, the local part is hidden.
    by_id = {c["customer_id"]: c for c in observation["customers"]}
    assert by_id["C-1001"]["name"] == "Northwind Labs"
    assert by_id["C-1001"]["email"] == "a***@northwind.example"

    # A service-account principal identifies the revoked/active grant, so it is kept as it is.
    assert {"svc-legacy-sync", "svc-fulfillment"} <= {g["principal"] for g in observation["access_grants"]}

    # The approved snapshot in the database still holds the real addresses; only the tool result is masked.
    with db.transaction() as conn:
        stored = q.load_snapshot(conn, fx.SNAPSHOT_ID)["content"]["customers"]
    assert {c["email"] for c in stored} >= {"ap@northwind.example", "billing@juniper.example"}
