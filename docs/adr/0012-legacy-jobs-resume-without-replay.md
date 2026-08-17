# Legacy Jobs Resume Without Replay

New Jobs use Job Runs directly, while unfinished legacy Jobs first use Checkpoint Reconstruction and then resume from their canonical artifacts. Reconstruction is read-only, never repeats image work or external submissions, leaves completed Jobs untouched, and stops instead of writing when the existing state cannot be reconciled safely.
