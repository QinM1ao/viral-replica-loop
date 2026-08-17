# Plugin and Client Workspace Are Separate

The Viral Replica Plugin is an immutable, versioned product that may operate multiple external Client Workspaces, while each Client Workspace owns all mutable client references, Jobs, run state, generated artifacts, and deliveries. This adds an explicit initialization and workspace-selection boundary, but prevents plugin installation or upgrade from overwriting client data and allows the same plugin package to be delivered unchanged to different clients.
