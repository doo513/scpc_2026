# Typed Fact and Record Contract

- JSON objects and records are frozen before semantic use.
- RecordAdapterRegistry covers every known RecordType and preserves UNKNOWN/MISSING/INVALID states.
- Conflicting structured facts remain CONFLICTED and are not relabelled as active constraints.
- Array order is not chronology; explicit turn/timestamp/relation metadata owns chronology.
