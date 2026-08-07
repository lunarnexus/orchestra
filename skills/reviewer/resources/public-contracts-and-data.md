# Public Contracts and Data

Identify every affected consumer, reader, writer, serialized form, and compatibility window.

Check relevant surfaces:

- public APIs, CLI arguments and output, configuration keys and defaults
- plugin, adapter, protocol, and external integration contracts
- schemas, migrations, persisted records, caches, and serialized artifacts
- validation and error behavior visible to callers
- packaging, generated assets, and documentation required to use the contract

For data changes, inspect old-to-new migration, new reads and writes, mixed-version behavior, partial failure, restartability, deployment order, rollback, and preservation of existing data. Destructive behavior requires explicit approval.

Report a compatibility finding only with an affected consumer or documented contract. Do not demand backward compatibility for an explicitly approved break, but require the approved migration and communication path.

Watch for public behavior changes hidden as cleanup, rename, refactor, or type tightening. Suggest the smallest compatible transition rather than a broader versioning framework.
