# Issue tracker: Local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments append under a `## Comments` heading

## Publishing

When a skill says to publish to the issue tracker, create or update the matching file under `.scratch/<feature-slug>/`.

## Wayfinding

- Map: `.scratch/<effort>/map.md`
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`
- Ticket type: `Type: research|prototype|grilling|task`
- Ticket status:
  `Status: ready-for-agent|claimed|review-ready|afk-blocked|resolved`
- Blocking: `Blocked by: NN, NN`
