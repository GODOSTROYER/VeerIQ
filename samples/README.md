# Inventory recovery samples

The three canonical sample packs live under [`backend/samples/import_recovery/`](../backend/samples/import_recovery/), where the importer loads them directly. This index avoids maintaining duplicate copies.

- [Warehouse stock locations](../backend/samples/import_recovery/warehouse_bins/README.md)
- [Medical asset supplies](../backend/samples/import_recovery/medical_assets/README.md)
- [Subscription seat inventory](../backend/samples/import_recovery/subscription_seats/README.md)

Each pack describes its synthetic incident, approved snapshot, and separate current authority record. See [the adapter interface](../docs/architecture.md) for the shared execution and safety boundaries.
