# Plugin Root Uses the Canonical Plugin Name

The formal Plugin Package root is named `shotloom/`, exactly matching the normalized `name` in `.codex-plugin/plugin.json`. The source repository may retain its existing checkout folder name because it builds the package rather than serving as the package root. The generic placeholder `plugin/` is not used as the deliverable root because Plugin Creator requires the directory name and manifest name to match. `workspace-dev/` remains outside the built plugin package and is never delivered with it.
