# Bounded Artifact Lifecycle

Pre-Seedance replacement keeps the current handoff plus one rollback version
outside the active Job directory. A later replacement overwrites that rollback
slot instead of creating another timestamped full-media archive. Existing
legacy archives are left untouched until a read-only retention preview has
identified what can be reclaimed.

This trades unlimited historical recovery for predictable storage and runtime.
One rollback version still protects the common “the new pack is worse” case,
while keeping history outside active QC discovery prevents reruns from getting
slower merely because the Job has been revised many times.

Local or manual final-video repair follows the same rule. A reviewed candidate
must be promoted with:

```bash
python3 tools/local_repair_lifecycle.py promote \
  --job-dir output/<job-id> \
  --candidate output/<job-id>/local_repair/candidate.mp4 \
  --report output/<job-id>/local_repair/repair_report.json \
  --confirm-job-id <job-id>
```

The command verifies that the PASS report still binds both the current master
and candidate, requires `paid_tasks_submitted=0`, atomically replaces
`final/final_video.mp4`, removes the promoted duplicate candidate, and rotates one
rollback under `output/.history/<job-id>/rollback/local_repair/`. Delivery
refuses a final master that matches local repair evidence without a current
lifecycle manifest. After promotion, finishing, subtitle handling, and final QC
must bind the new master before delivery can pass again.

Legacy subtitle trials are not unlocked merely because they look redundant.
`artifact_lifecycle.py migrate-subtitle-cleanup` explicitly binds the current
source and output hashes first; any later file change locks cleanup again.
