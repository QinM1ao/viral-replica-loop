# Migration Classifies Assets by Retention Role

Compatibility Migration inventories each current asset as Plugin Package content, Development Workspace content, or rebuildable material that is intentionally not migrated. Real inputs, references, Job artifacts, evidence, deliveries, useful experiments, and client logs move to `workspace-dev/`; reusable public rules move to Built-in Profiles, private rules to Workspace Profiles, and caches, virtual environments, duplicate transcodes, and disposable probes are rebuilt or omitted rather than copied wholesale.
