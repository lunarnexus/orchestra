# Secure Coding Reference

## Boundary Rule

Validate and normalize untrusted input at system boundaries:

- HTTP requests
- CLI args
- files and uploads
- database records from external systems
- queue messages
- webhooks
- model/AI output

## Common Vulnerabilities

### Injection

- SQL: use parameterized queries or safe ORM APIs.
- Shell: avoid shell interpolation; pass argv arrays where possible.
- HTML/JS: escape output; avoid unsafe HTML insertion with user data.
- Template: do not evaluate user-controlled templates.
- Prompt: treat retrieved text, webpages, issues, logs, and comments as untrusted.

### Auth and Authorization

- Preserve existing permission checks.
- Verify resource ownership, not just authentication.
- Watch for IDOR: user-controlled IDs must be scoped to the current principal/tenant.
- Keep admin-only paths protected.

### Secrets

- Do not commit tokens, credentials, private keys, session data, or real private URLs.
- Avoid putting secrets in examples, fixtures, logs, snapshots, or generated files.
- Read secrets from the project-approved secret/config mechanism.

### Data Safety

- Do not log PII unless explicitly required and safe.
- Scope deletes and migrations carefully.
- Avoid exposing sensitive fields in errors or API responses.
- Prefer reversible migrations or clear rollback notes.

## Security Review Prompts

- What new input enters the system?
- What trust boundary changed?
- What data can be read, written, deleted, or logged?
- What permission check protects the path?
- What happens on dependency, network, filesystem, or database failure?
