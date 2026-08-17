# Workspaces Are Disposable without Plugin Dependency

The Plugin Package and every future Workspace Bootstrap must continue to work when `workspace-dev/` or any Client Workspace is absent or deleted; no workflow rule, executable dependency, Built-in Profile, or required test may be discovered from historical run directories. Deleting a workspace deliberately deletes its references, Job Archives, evidence, and deliveries unless they were exported first, so Workspace Independence protects the product and future work rather than promising recovery of removed client data.
