# Dependencies and Integrations

First establish why existing project facilities are insufficient. A dependency or integration is unjustified when it adds more maintenance and failure surface than the assigned behavior requires.

For dependencies, check:

- package identity, maintained version, license, compatibility, and advisory evidence
- manifest and lockfile coherence
- only required package features and intentional transitive changes
- platform, build, packaging, and generated-file impact
- whether an upgrade or removal changes public behavior

For external services, SDKs, and protocols, check:

- verified request, response, authentication, pagination, and version contracts
- bounded timeouts
- retries limited to safe transient operations with appropriate idempotency
- boundary validation of remote data
- actionable errors without secret or payload leakage
- representative success and failure tests through the project abstraction

Do not impose arbitrary ecosystem policy that the project has not adopted. Report concrete compatibility, reliability, maintenance, or supply-chain impact.
