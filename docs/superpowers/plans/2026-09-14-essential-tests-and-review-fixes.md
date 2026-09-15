# Essential tests and review fixes

Scope: user explicitly requested at most 30 collected tests across the entire
repository, followed by fixes for both review findings. Work in the current
checkout to preserve the reviewed uncommitted changes.

1. Keep 28 essential existing cases covering authorization, independent evidence
   checks, bounded execution, session persistence, market-data delivery/replay,
   and policy promotion. Remove remaining cases and unused support code; retain
   no hidden/deselected legacy suite. Replace broad parameter matrices with one
   representative case where necessary. Verify the 28-case suite before fixes.
2. Add two regression tests: a successful engine trace must not override a
   contradiction gap; offline replay must retain a final active-policy-change
   veto. Verify both tests fail against the reviewed implementation.
3. In capability_mining.py classify engine failures from the gap itself rather
   than mere engine tool use. In rsi_cycle.py separately validate comparative
   eligibility and the final saved decision/outcome, preserving final vetoes.
4. Document the retained coverage and per-phase turn semantics. Run all 30 tests,
   inspect the final diff, and check whitespace. No live model requests or policy
   changes in the project are part of this work.
