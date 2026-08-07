# Finding validation

Before reporting HIGH or MEDIUM:

1. Re-read the current line and trace the complete path from attacker-controlled input to impact.
2. State the required attacker capability and preconditions.
3. Inspect callers, callees, configuration, and framework behavior that could block the path.
4. Distinguish introduced or directly affected behavior from unrelated baseline risk.
5. Prefer a safe local proof or focused regression check when it reduces uncertainty.
6. Calibrate severity to demonstrated reachability and impact, not the vulnerability category name.
7. Give the smallest remediation that breaks the attack path.

If reachability, attacker control, or impact cannot be established, omit the finding and record a bounded residual risk only when useful.
