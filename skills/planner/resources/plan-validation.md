# Plan validation

Run before returning a non-blocked production plan.

- Requirement coverage: every in-scope requirement maps to a slice, evidence item, or blocker.
- Placeholder scan: remove TBD, TODO, “add validation,” “handle edge cases,” “write tests,” and “similar to previous” without specifics.
- Interface consistency: function, file, config, schema, and command names match across slices.
- Dependency check: every `parallel-safe` slice satisfies the independence rule.
- Research contract: every Researcher assignment is a bounded evidence unit, not a request to plan, design, decompose implementation, or decide product behavior.
- Research scope and answer shape: every Researcher assignment includes exact source scope, evidence acceptance, enough-evidence target, and return fields.
- Research ledger: `Research used` and `Research still needed` stay compact and include only plan-changing facts or blockers.
- Research classification: discoverable facts, user-owned decisions, and spike questions are classified separately.
- Research barrier: every dispatched evidence unit has a terminal result before dependent decisions appear.
- Required Researcher evidence: if the task required Researcher evidence, or the plan declares an evidence unit required, dependent decisions appear only after a successful Researcher result. Failed, rejected, timed-out, empty, or missing Researcher results force `blocked`.
- Evidence scope: accepted citations stay inside the declared source scope.
- Verification check: every implementation slice has a stop condition and verification path.
- Scope check: every planned file is accounted for; unrelated cleanup is excluded or explicitly deferred.
