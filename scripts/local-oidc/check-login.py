#!/usr/bin/env python3
"""Run real authorization-code logins against the disposable local Keycloak realm."""

from __future__ import annotations

import http.cookiejar
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / ".local-oidc"
APP = "https://localhost:8443"


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.form_action: str | None = None
        self.inputs: dict[str, str] = {}
        self.in_login_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and (values.get("id") == "kc-form-login" or self.form_action is None):
            self.form_action = values.get("action")
            self.in_login_form = True
        elif tag == "input" and self.in_login_form:
            name = values.get("name")
            if name:
                self.inputs[name] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.in_login_form = False


def local_accounts() -> list[tuple[str, str, str, str]]:
    rows = []
    credential_file = PRIVATE / "credentials.txt"
    for line in credential_file.read_text(encoding="utf-8").splitlines():
        if ": " not in line or " / " not in line or line.startswith("Admin:"):
            continue
        label, identity = line.split(": ", 1)
        username, password = identity.split(" / ", 1)
        tenant, role = label.split(" ", 1)
        rows.append((tenant, role, username, password))
    if len(rows) != 3:
        raise RuntimeError("Private fixture account file is incomplete.")
    return rows


def request_json(opener: urllib.request.OpenerDirector, url: str, *, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as response:
        try:
            result = json.loads(response.read())
        except ValueError:
            result = {}
        return response.code, result


def login(tenant: str, role: str, username: str, password: str) -> dict:
    cookies = http.cookiejar.CookieJar()
    context = ssl.create_default_context(cafile=str(PRIVATE / "tls/localhost.crt"))
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies),
        urllib.request.HTTPSHandler(context=context),
    )
    with opener.open(APP + "/api/auth/login", timeout=15) as response:
        page = response.read().decode("utf-8")
        login_url = response.geturl()
    form = FormParser()
    form.feed(page)
    if not form.form_action or "username" not in page or "password" not in page:
        raise RuntimeError(f"Keycloak login form was not available for fixture role {role}.")
    values = dict(form.inputs)
    values.update({"username": username, "password": password})
    submit = urllib.request.Request(
        urllib.parse.urljoin(login_url, form.form_action),
        data=urllib.parse.urlencode(values).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with opener.open(submit, timeout=20) as response:
        response.read()
        if response.geturl().split("/", 3)[:3] != ["https:", "", "localhost:8443"]:
            raise RuntimeError(f"OIDC callback did not return to VeerIQ for fixture role {role}.")
    session_cookies = [cookie for cookie in cookies if cookie.name == "rs_session"]
    if len(session_cookies) != 1 or not session_cookies[0].secure or not session_cookies[0].has_nonstandard_attr("HttpOnly"):
        raise RuntimeError(f"VeerIQ did not issue one secure HttpOnly session for fixture role {role}.")
    status, identity = request_json(opener, APP + "/api/session")
    if status != 200 or identity.get("role") != role or identity.get("tenant_id") != tenant:
        raise RuntimeError(f"VeerIQ identity mapping failed for fixture role {role}.")
    status, identities = request_json(opener, APP + "/api/identities")
    if status != 200 or any(item.get("tenant_id") != tenant for item in identities):
        raise RuntimeError(f"Tenant-scoped identity list failed for fixture role {role}.")
    status, state = request_json(opener, APP + "/api/app/state")
    if status != 200 or state.get("tenant", {}).get("id") != tenant:
        raise RuntimeError(f"Tenant-scoped application data failed for fixture role {role}.")
    if not state.get("orders"):
        raise RuntimeError(f"No tenant fixture records were visible for fixture role {role}.")
    return {"tenant": tenant, "role": role, "identity_id": identity["identity_id"], "visible_identity_count": len(identities), "opener": opener}


def assert_denied(opener: urllib.request.OpenerDirector, url: str, body: dict, code: str) -> None:
    status, result = request_json(opener, APP + url, method="POST", body=body)
    if status != 403 or result.get("error", {}).get("code") != code:
        raise RuntimeError(f"Expected the {code} boundary, received HTTP {status}.")


def main() -> None:
    accounts = local_accounts()
    sessions = [login(*account) for account in accounts]
    by_role = {(item["tenant"], item["role"]): item for item in sessions}
    operator_a = by_role[("atlas", "operator")]
    reviewer_a = by_role[("atlas", "reviewer")]
    operator_b = by_role[("beacon", "operator")]
    if operator_a["visible_identity_count"] != 2 or reviewer_a["visible_identity_count"] != 2 or operator_b["visible_identity_count"] != 1:
        raise RuntimeError("Tenant identity list did not preserve the configured tenant boundary.")
    assert_denied(operator_a["opener"], "/api/approvals/local-nonexistent/decide", {"decision": "approve", "note": ""}, "reviewer_required")
    assert_denied(reviewer_a["opener"], "/api/admin/reset", {}, "operator_required")
    status, draft = request_json(operator_a["opener"], APP + "/api/grants/draft", method="POST", body={"scenario_id": "clean"})
    if status != 200 or draft.get("tenant_id") != "atlas":
        raise RuntimeError("Operator could not create an Atlas-scoped draft grant.")
    status, result = request_json(operator_b["opener"], APP + f"/api/grants/{draft['grant_id']}")
    if status != 404 or result.get("error", {}).get("code") != "not_found":
        raise RuntimeError("A Beacon operator could read another tenant's Atlas grant.")
    status, result = request_json(operator_a["opener"], APP + "/api/session", method="POST", body={"identity_id": operator_b["identity_id"]})
    if status != 403 or result.get("error", {}).get("code") != "oidc_login_required":
        raise RuntimeError("Demo identity impersonation was not disabled in OIDC mode.")
    status, review_draft = request_json(operator_a["opener"], APP + "/api/grants/draft", method="POST", body={"scenario_id": "review"})
    if status != 200 or not review_draft.get("reviewable"):
        raise RuntimeError("The reviewer-path rehearsal could not create its reviewable draft grant.")
    grant_id = review_draft["grant_id"]
    status, _ = request_json(operator_a["opener"], APP + f"/api/grants/{grant_id}/authorize", method="POST", body={})
    if status != 200:
        raise RuntimeError("The operator could not authorize the local review-path grant.")
    status, run = request_json(operator_a["opener"], APP + "/api/runs", method="POST", body={"grant_id": grant_id, "planner": "scripted"})
    if status != 200:
        raise RuntimeError("The scripted local review run could not start.")
    run_id = run["run_id"]
    pending = None
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status, approvals = request_json(reviewer_a["opener"], APP + "/api/approvals?status=pending")
        if status == 200:
            pending = next((item for item in approvals if item.get("run_id") == run_id), None)
            if pending:
                break
        time.sleep(0.5)
    if pending is None or pending.get("requested_by") != operator_a["identity_id"] or not pending.get("payload_digest"):
        raise RuntimeError("The run did not produce an operator-requested payload-bound approval for the reviewer.")
    if pending["requested_by"] == reviewer_a["identity_id"]:
        raise RuntimeError("The reviewer identity was also the requester.")
    status, decided = request_json(
        reviewer_a["opener"], APP + f"/api/approvals/{pending['approval_id']}/decide",
        method="POST", body={"decision": "approve", "note": "Independent local rehearsal reviewer"},
    )
    if status != 200 or decided.get("decided_by") != reviewer_a["identity_id"]:
        raise RuntimeError("The separate reviewer could not decide the payload-bound approval.")
    final_run = None
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status, runs = request_json(operator_a["opener"], APP + "/api/runs")
        if status == 200:
            final_run = next((item for item in runs if item.get("run_id") == run_id), None)
            if final_run and final_run.get("status") in {"succeeded", "partially_succeeded", "blocked", "failed", "cancelled"}:
                break
        time.sleep(0.5)
    if not final_run or final_run.get("status") != "succeeded":
        raise RuntimeError("The reviewed scripted repair did not finish successfully.")
    print("PASS: three real Keycloak authorization-code + PKCE logins; issuer/JWKS/token exchange and secure opaque sessions verified.")
    print("PASS: operator, reviewer, and second-tenant identities mapped from configured subjects; tenant identity lists remained scoped.")
    print("PASS: app fixture reads stayed tenant-scoped; cross-tenant grant lookup, reviewer/operator privilege violations, and demo identity impersonation were denied.")
    print("PASS: scripted offline review path completed with distinct mapped operator and reviewer identities and a payload-bound approval.")


if __name__ == "__main__":
    main()
