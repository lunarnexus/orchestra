# Secrets and sensitive data

Identify the sensitive value, who may observe it, every new persistence or disclosure channel, and retention lifetime.

Inspect source, fixtures, logs, errors, URLs, telemetry, client responses, caches, temporary files, and generated artifacts. Distinguish real credentials from obvious inert examples.

Check that redaction happens before serialization and transport, failures do not reveal raw values, and access is least-privileged. Treat hashes or encodings as disclosure when they remain reusable credentials or linkable private data.

Report the concrete observer and consequence. Do not report keyword matches without validating that the value is secret and reachable.
