# Sandcastle review standards

- Follow root `AGENTS.md`, `CONTEXT.md`, relevant ADRs, and ticket acceptance
  criteria.
- Make the smallest complete change. Do not refactor unrelated code.
- Use tests at stable seams and retain all existing behavior unless the ticket
  explicitly changes it.
- Treat missing evidence, credentials, customer media, provider calls, paid
  actions, and undeclared machine dependencies as hard failures.
- Never modify `.sandcastle/`, private `.scratch/` tickets, or the sibling
  Development Workspace from an implementation branch.
- A reviewer is read-only. A fresh bounded repair session may repair findings;
  it must not inherit the implementation session's accumulated test output.
