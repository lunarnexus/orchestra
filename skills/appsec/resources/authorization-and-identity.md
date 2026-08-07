# Authorization and identity

For each privileged action, identify the subject, requested object, tenant or owner, policy decision, and enforcement point.

- Distinguish authentication from authorization.
- Trace every route to the privileged operation; UI checks are not enforcement.
- Verify object-level, tenant-level, and role-level checks use trusted identity state.
- Check session creation, rotation, expiry, revocation, token audience, and replay where changed.
- Look for confused-deputy behavior where a trusted service acts on attacker-selected resources.
- Treat default allow, missing ownership checks, and authorization after side effects as material when reachable.

Report the exact unauthorized action and asset, not a generic access-control label.
