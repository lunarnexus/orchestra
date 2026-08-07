# Test-Driven Development

Use TDD for every production change.

For each behavior:

1. Write one test through the narrowest stable public interface.
2. Run it and confirm RED demonstrates the expected missing behavior rather than broken test setup, tooling, or environment.
3. If it passes immediately, rewrite it so it proves the change is absent.
4. Implement only enough production code for GREEN.
5. Run the focused test and require no new relevant warnings; record baseline warnings separately.
6. Refactor while green, then rerun the test.
7. Repeat for the next behavior, then run affected tests.

A pure refactor begins from passing characterization coverage and stays green in small steps. A disposable spike remains outside production; promotion starts a new TDD production slice.

If an automated test cannot drive the assigned production change, return a blocker. Never substitute a post-implementation test or a previously passing test for Red evidence.
