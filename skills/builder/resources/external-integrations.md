# External Integrations

- Use verified primary documentation or approved `RESEARCH.md` findings for contracts and limits.
- Confirm authentication, request/response shapes, errors, pagination, rate limits, and version behavior.
- Set bounded timeouts; retry only safe transient operations with project-standard backoff.
- Validate remote data at the boundary and avoid leaking credentials or sensitive payloads.
- Preserve actionable error context without exposing secrets.
- Test through the project abstraction with representative success and failure responses.
- Return any assumption that still depends on the live service or environment.
