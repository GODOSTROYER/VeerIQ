#!/usr/bin/env python3
"""Read-only counterfactual: identify legitimate fixture decisions a blunt restore reverses."""
import argparse
import json
from pathlib import Path
from rewindsafe.workflows.rewindsafe import fixture


def comparison():
    snapshot = fixture.snapshot_content()
    harms = []
    current_customers = {r['customer_id'] for r in fixture.current_customers()}
    for row in snapshot['customers']:
        if row['customer_id'] not in current_customers:
            harms.append({'record': row['customer_id'], 'decision': 'customer erased', 'current': 'absent', 'blunt_restore': 'present', 'selective_requirement': 'absent'})
    current_orders = {r['order_id']: r for r in fixture.current_orders()}
    for row in snapshot['orders']:
        current = current_orders.get(row['order_id'])
        if current is None:
            harms.append({'record': row['order_id'], 'decision': 'order deleted', 'current': 'absent', 'blunt_restore': 'present', 'selective_requirement': 'absent'})
        elif current['updated_by'] == fixture.FULFILLMENT_WRITER and current['status'] != row['status']:
            harms.append({'record': row['order_id'], 'decision': 'shipment completed after snapshot', 'current': current['status'], 'blunt_restore': row['status'], 'selective_requirement': current['status']})
    grants = {r['grant_id']: r for r in fixture.ACCESS_GRANTS_CURRENT}
    for row in snapshot['access_grants']:
        current = grants.get(row['grant_id'])
        if current and current['status'] == 'revoked' and row['status'] == 'active':
            harms.append({'record': row['grant_id'], 'decision': 'access revoked', 'current': 'revoked', 'blunt_restore': 'active', 'selective_requirement': 'revoked'})
    return {'source': 'read-only synthetic fixture counterfactual; no restore executed', 'snapshot_id': fixture.SNAPSHOT_ID, 'snapshot_digest': fixture.snapshot_digest(), 'modeled_tables': ['customers','orders','access_grants'], 'legitimate_decisions_reversed': len(harms), 'comparisons': harms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = comparison()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
