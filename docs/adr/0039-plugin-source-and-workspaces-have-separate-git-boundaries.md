# Plugin Source and Workspaces Have Separate Git Boundaries

The canonical `viral-replica/` Plugin Package directory is the Plugin Source Repository, while `workspace-dev/` and every Client Workspace are siblings outside that Git repository rather than ignored subdirectories within it. This prevents ordinary source-control operations from capturing client references, generated media, evidence, credentials, or run state, and lets one clean plugin commit identify a release package independently of workspace cleanup, backup, or deletion.
