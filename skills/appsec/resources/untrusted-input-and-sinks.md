# Untrusted input and sensitive sinks

Trace attacker-controlled bytes to the exact sink and preserve transformations along the path.

- SQL: require parameterization for values and allowlists for identifiers.
- Shell/process: prefer fixed executable plus argument vector; identify shell parsing explicitly.
- HTML/templates/logs: use context-correct encoding, not generic sanitization.
- Filesystem: resolve and constrain paths before access; account for absolute paths, traversal, symlinks, and race-sensitive writes.
- Network/URLs: constrain scheme, host, port, redirects, and address resolution when destinations are untrusted.
- Parsing/deserialization: distinguish data-only formats from object construction or code execution.

Validation must constrain the representation the sink interprets. Reject findings when the input is trusted by an enforced boundary or the sink API removes the claimed interpretation.
