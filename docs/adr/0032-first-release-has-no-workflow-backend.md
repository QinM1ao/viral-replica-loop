# First Release Has No Workflow Backend

The first Viral Replica Plugin uses Local Plugin Execution: Codex Skills invoke the packaged local engine for orchestration, media processing, state, and QC, while external model providers are called directly with client-owned Service Authorization. There is no vendor workflow backend, credential proxy, or hosted job queue; this keeps installation direct and preserves the validated execution path, at the cost of requiring each client machine to satisfy the local runtime contract.
