# Workspace Separation Uses Compatibility Migration

The repository will reach the plugin/workspace architecture through a Compatibility Migration: introduce shared path boundaries first, prove the old and new layouts behave equivalently, then make the new layout the default. This temporarily carries a bounded compatibility path, but avoids a big-bang directory rewrite, preserves historical Job evidence, and prevents structural cleanup from silently changing model inputs, stage routing, approvals, QC, or deliveries.
