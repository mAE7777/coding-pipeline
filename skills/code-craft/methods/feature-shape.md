### Feature: data shape and throughput checkpoint

The two parts of pstack's Feature playbook that this pipeline's build uses. `/dev` owns the rest of the build.

**Data shape first.** Before anyone writes logic, name the data shape and its organizing structure per **principle-model-the-domain**: a state machine over scattered booleans, a table/registry over branching, a typed model over repeated shape assumptions.

**Throughput checkpoint.** Write the throughput checkpoint as four items. A dimension that genuinely does not apply (single file, no fan-out) keeps its item with `n/a: <reason>` rather than being dropped:
   - **Blocking first steps.** Gates run before fan-out.
   - **Independent workstreams.** Disjoint files, services, or layers parallelize. Shared writes serialize.
   - **Shared mutable state.** Default to splitting the target (the **separate-before-serializing-shared-state** principle skill). Serialize only for real invariants.
   - **Smallest safe decomposition.** If one worker is best, name why.

Code-coupled work (one feature, one migration) goes to a single owner with the checkpoint inline. That owner fans out internally after the blocking phase. Parent-level fan-out is for slices that produce independent artifacts (audits, cross-subsystem investigations, competing experiments). Rewrite the checkpoint at phase boundaries. Spawn a fresh owner rather than chaining interrupts.
