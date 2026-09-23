## Qualification and release
- [x] 1. Reverify frozen source, image, prior seals and live OFF baseline.
- [x] 2. Verify fresh PostgreSQL backup and isolated restore without production writes to application tables or schema.
- [x] 3. Qualify exact candidate PostgreSQL startup, local extensions, protected data, sequences, synthetic legacy/v2 retry/recovery, restart and predecessor compatibility.
- [x] 4. Implement manifest-bound admission and operation-specific first-start/replacement/recovery artifacts.
- [x] 5. Run actual isolated Engine gate, successful cutover, restart/recreation, injected failure/recovery and negative-boundary tests; independently review final artifacts.
- [x] 6. Recheck actual production baseline and fresh backup; perform authorized Beta-only OFF replacement once.
- [x] 7. Verify exact runtime, OFF/no-plan, unchanged protected records and other services, signer renewal, retained predecessor, cleanup and preservation; finalize operations documentation.

The external release manifest is written after operations documentation is finalized. Final validation/archive requests and a single retry were blocked before execution, so this change remains in the separate operations copy; no final archival is claimed. Initial strict change validation and 66 main specs passed. See the external openspec-final-result.json for this administrative limitation. Product-source and activation authority are unaffected.
