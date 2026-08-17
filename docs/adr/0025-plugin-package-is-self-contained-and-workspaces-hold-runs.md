# Plugin Package Is Self-Contained and Workspaces Hold Runs

The development product root separates one self-contained `viral-replica/` Plugin Package from a non-delivered sibling `workspace-dev/` Development Workspace. All live or historical Job inputs, generated images, audio, videos, QC evidence, and deliveries belong to workspaces, while every Skill, workflow rule, executable component, Built-in Profile, template, test, and operating document required to create and run a fresh workspace belongs to the Plugin Package; the plugin must operate without `workspace-dev/`.
