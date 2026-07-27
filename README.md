# orchestra

Project scaffold bootstrapped from the template.

## Getting Started

1. Copy this template to a new directory:
   ```bash
   cp -r . /path/to/new-project && cd /path/to/new-project
   ```
2. Replace all `[PLACEHOLDER]` values in every file. Search for `PLACEHOLDER` across the project.
3. Initialize Git and commit the baseline:
   ```bash
   git init && git add -A && git commit -m "Initial commit"
   ```
4. Establish baseline tests before writing feature code (see AGENTS.md).
5. Run CodeGraph initialization **inside your copied project**, not inside this template:
   ```bash
   hermes codegraph init
   ```

## Structure

```
.
├── .env.example      # Required environment variables
├── .gitignore        # Ignored files (customize for your project)
├── .editorconfig     # Editor settings
├── AGENTS.md         # AI coding agent rules and conventions
├── CHANGELOG.md      # Version history
├── FOUNDATION.md     # Core concepts, architecture decisions, domain model
├── PLAN.md           # Current implementation plan
├── README.md         # This file
└── docs/             # Project documentation
```

## Notes

- `.gitignore` excludes `data/`. If your project tracks data files, remove or narrow that rule.
- Every project should customize `.gitignore`, `.env.example`, and language-specific tooling before first commit.
