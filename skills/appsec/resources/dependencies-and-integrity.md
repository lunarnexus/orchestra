# Dependencies and integrity

Establish what code or artifact becomes trusted, who controls its source, and how identity and integrity are verified.

- Inspect manifest and lockfile together.
- Verify registries and sources for packages, models, datasets, adapters, prompts, and plugins; check pinned identity, hashes or signatures, provenance, and update policy where relevant.
- Check install/build hooks, model or data loading, and newly reachable transitive behavior.
- For plugins and updates, verify authenticity before loading or execution.
- For training, fine-tuning, retrieval, and memory inputs, identify who can poison trusted state and how integrity or lineage is enforced.
- For security configuration, identify whether defaults widen exposure or disable an existing control.

A dependency change is not a vulnerability by itself. Report a concrete malicious, compromised, or substituted artifact path and resulting impact.
