# Workspaces Have Versioned Recoverable Schemas

Every Client Workspace declares a Workspace Schema version that the Viral Replica Plugin checks before writing. Compatible versions run directly; incompatible upgrades require an explicit previewed and recoverable migration that preserves historical Job Archives, Reference Bindings, and accepted evidence, while an older plugin must refuse writes to a newer schema rather than attempt a destructive downgrade.
