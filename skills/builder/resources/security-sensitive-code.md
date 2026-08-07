# Security-Sensitive Code

Identify the trust boundary, protected asset, untrusted inputs, and required authorization before editing.

- Validate at the boundary and encode or parameterize at the sink.
- Preserve least privilege and fail closed.
- Keep secrets out of source, output, logs, fixtures, and snapshots.
- Avoid shell interpolation, unsafe path construction, permissive deserialization, and unrestricted network targets.
- Preserve authentication, authorization, integrity, and audit behavior.
- Add tests for the relevant denied or malformed path as well as success.

Do not weaken a control to make a test pass. Return an explicit blocker when the approved design cannot satisfy the security invariant.
