# Live ArmorIQ HOLD setup and rehearsal

**Status: no ArmorIQ HOLD has been observed.** A >USD5,000 rule was reported activated on 2026-10-12, but the isolated $12,400 call made afterwards still returned ALLOW ([hold-rule-first-check.json](evidence/merged/hold-rule-first-check.json)), and the amount condition could not be applied in this workspace's dashboard. The steps below remain the plan for capturing a real hold, approval, rejection and timeout; the gateway code for that round trip exists and is unit-tested with fakes only.

## Dashboard steps

Use the existing recovery agent and its currently assigned policy; do not replace its allowlist or access-restoration deny.

1. Open the organization containing `rewindsafe-recovery` and inspect its active target-agent policy assignment.
2. If the financial Policy Studio is available, open `/dashboard/armorpay/studio`, select that agent under Metadata, and configure the recovery apply tool under Tool Configuration with its server-derived `amount` field and USD currency.
3. Under Amount Threshold, set Hold Threshold to 5000 and choose an authorized reviewer under Approval Workflow. Ensure smaller approved repairs remain allowed and `restore_access_grant` remains blocked.
4. Inspect the generated policy preview and deploy the rule. Verify target assignment and priority; a form draft is not an active policy.
5. On the isolated $12,400 recovery rehearsal, look for a real held plan and pending delegation in Plans. Approve the first request, reject the second, and leave the third undecided for the timeout test.

The field names above are documented for ArmorPay Policy Studio; availability in this account must be confirmed in its UI. A generic policy editor may expose different controls; do not upload the repository's old proposed policy JSON as a verified schema.

Official references: [Policy Studio](https://docs.armoriq.ai/armorpay/policy-studio), [SDK sessions and approval modes](https://docs.armoriq.ai/sdk/sessions), [held plans dashboard](https://docs.armoriq.ai/armoredu/dashboard).

## Evidence requirements

Save live `action=hold`, nonempty delegation ID, actual await_approval result, current-state revalidation, and durable effect count. Separate sponsor approval from the application's second reviewer. Reject/timeout must record zero repair commits. SDK `local` mode cannot complete sponsor approvals; this rehearsal uses `sdk`.
