# Job Runs Resume From Checkpoints

A restarted Job Run resumes from current Run Checkpoints and canonical artifacts instead of restarting completed stages. Completed image work and external submissions are never repeated, only the smallest incomplete safe work resumes, and conflicting state stops writeback until the canonical artifacts can restore one truthful state.
