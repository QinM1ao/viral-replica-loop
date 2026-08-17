# First Use Selects the Client Workspace

Private Folder Installation installs only the managed Viral Replica Plugin. On the first `viral-replica` use, Workspace Bootstrap asks the client to create or adopt one Client Workspace, with `~/Documents/viral-replica-workspace/` as the default new location and an explicit option to choose another folder. The selected workspace location is persisted outside the replaceable Plugin Package, later uses reopen it automatically, plugin upgrades never overwrite it, and deleting it does not damage the installed plugin.
