# Job Intake is one append-only path

All formal Jobs are created through one Job Intake module. Explicit-task and
inbox commands are adapters only. Job Intake validates inputs before writes,
allocates IDs across both `jobs.csv` and existing output directories, preserves
measured source duration by default, writes per-Job intake/profile evidence,
and never rebuilds or overwrites the existing queue.
