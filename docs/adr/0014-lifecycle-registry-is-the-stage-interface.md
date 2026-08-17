# Lifecycle Registry is the stage interface

`rules/STAGE_RULES.json` remains the persisted lifecycle data. The Lifecycle
Registry is its only interpretation interface for initial state, terminal
state, ordered exact/prefix/contains matching, canonical execution stage, and
the five user-visible progress stages. Runners and intake adapters must not
keep independent lifecycle maps. Legacy partial rule fixtures are read through
an explicit compatibility path and are never used to shape new Jobs.
