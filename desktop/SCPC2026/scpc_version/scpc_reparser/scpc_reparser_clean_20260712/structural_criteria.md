# Structural Criteria Contract Status

This file separates official submission contracts from runtime invariants and
project-level safety goals. Passing a finite corpus is never reported as proof of a
universal semantic property.

## Criterion A — execution and unknown-data safety

1. **A(a), runtime regression:** all 700 published screening tasks execute without
   an error and produce schema-valid answers.
2. **A(b), design policy:** an outbound disclosure containing an unregistered
   object type or property is represented as `UNKNOWN` and fails closed through an
   active `HARD` constraint, `control=hold`, and `content_scope.mode=none`.

A(a) is finite regression evidence. A(b) is a conservative project policy requested
for this implementation, not a rule stated by the official schema.

## Criterion B — validator and decision legality

1. **B(a), runtime invariant:** every emitted answer passes the strict validator
   against the immutable `FinalDecision` used to build its projection.
2. **B(b), unresolved contract:** every valid input produces a legal decision.

The official materials provide an output schema but no exhaustive input JSON schema
or semantic oracle for every valid task. In this repository, tests may establish
legality only for the parser-supported task shape by checking the output schema,
available-action membership, and control/scope/plan invariants. They do not prove
B(b) for all possible inputs.

## Criterion C — dynamic HARD propagation

**Runtime invariant:** every activated constraint whose severity is `HARD` must
compile to a blocked Blueprint/disposition and ultimately to `control=hold`.

This detects complete propagation of constraints that were activated. It does not
prove that the rule system recognizes every real-world condition that ought to be
HARD.
