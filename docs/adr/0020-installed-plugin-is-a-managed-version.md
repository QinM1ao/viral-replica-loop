# Installed Plugin Is a Managed Version

The Viral Replica Plugin follows the Codex managed-plugin model: maintainers may modify the source package and publish a new version, while an installed copy is treated as a replaceable, versioned artifact rather than a client customization surface. Host filesystem permissions may make cached files physically editable, but supported client customization lives in the Client Workspace; this preserves upgrade and integrity expectations without pretending the distributed implementation is technically inaccessible.
