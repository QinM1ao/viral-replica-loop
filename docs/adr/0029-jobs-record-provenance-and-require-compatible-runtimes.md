# Jobs Record Provenance and Require Compatible Runtimes

Each Job records immutable Job Provenance covering its creating plugin version, workflow contract, Built-in and Workspace Profile versions, and Reference Binding. A newer plugin may resume the Job only when it explicitly supports that provenance and preserves its behavior; otherwise the Job requires its original compatible version or an explicit migration, while new plugin defaults apply only to new Jobs and no full plugin copy is stored inside each Job Archive.
