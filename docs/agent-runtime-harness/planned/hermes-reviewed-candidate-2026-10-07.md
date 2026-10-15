# Reviewed Hermes fork candidate — 2026-10-07

Branch `prep/hermes-waves-reviewed-20261007`, main frozen at `f1d285e4faf09aec1e6b973e307c439201248d0c`. Combined product freeze `b5fa078e1f5d27be42f6eb9592b2ce6f975a77c9`; this receipt changes documentation only.

| Reviewed dependency | Exact tip |
| --- | --- |
| Runtime, anchor and resident/writer | `4e4db3e0b7d88817865c496fdebd7108d3eca54a` |
| Runtime evidence wave | `f35900ff220ce0e4371147b15cf93293e8bb930e` |
| Job2 local helper moves/verdict table | `1d42960ab6f9385b30c22435b2b9922d4ff81e44` |
| Native chat fixture and hook finding | `5e7549091b0026ea96320b2222af990c4faaa162` |
| QA parity, already runtime ancestor | `d30264b544fa19fc7a43aea52d5c28e1d7da3856` |

All dependency tips and frozen main are ancestors. No conflicts or manual semantic resolution. Automatic merges joined `skill_resolution`'s reviewed metadata/default helpers and preparation epoch, the additive upstream ledger rows, and queue outcomes. Completed removals, five fresh evidence verdicts, current standing-stream field receipt and existing claims are preserved without duplicate titles.

## Independent original runtime claim accounting

Exact title matching against the original 41-row `runtime.json` manifest, with a verified deletion diff/commit for every absent title: **32 DONE, 1 REFUTED, 8 PENDING**. No inferred 42nd original row and no missing-title assumption without a deletion receipt.

- REFUTED: R017's old build-unknown assertion, scoped to the actual supported developer boot evidence.
- Concrete additive upstream-door prerequisites remain pending: R008, R010, R034; see [ownership design](runtime-wave2-ownership-2026-10-07.md). Their design is not a completed producer implementation.
- Five fresh evidence prerequisites remain pending: R003, R013, R018, R019, R021; see [evidence wave](runtime-evidence-wave4-2026-10-07.md). R013 retains the current standing-stream drain receipt and actual Launcher handoff remains unproved.
- Separate added anchor claim: DONE at `efad97d0952081213f2f352b967d333a8011f278`; not included in the original 41. Separate hook-isolation finding: PENDING in fork-hygiene queue; see [hook receipt](isolated-worktree-hook-home-2026-10-07.md).

Per-ID original title, queue line or deletion SHA, and separate claim receipts are in coordinator `outputs/hermes-reviewed-candidate-accounting.json`; reproduction `hermes-reviewed-candidate-accounting.py`. Historical progress status is retained there only as comparison, not current authority.

## Narrow combined proof

28 passed using the actual native anchor handler with the new request writer owner; real resident ProfileAgentRunner prewarm followed by run; two named helper test files for the automatic skill/default overlap and gateway import order; six exact repaired create/delete/resolve/refusal nodes in `test_chat_verbs_rpc`. Raw log: coordinator `outputs/hermes-reviewed-candidate-focused.log`. Initial selection typo collected no tests; exact nodes were corrected. Accounting first rejected a curly-apostrophe receipt decoded with the host locale; explicit UTF-8 receipt decoding fixed it, without queue edits.

All merges used per-command empty hooks and isolated homes. Primary untracked state, old runtime evidence/WIP, Job2 and other lanes' dirt preserved; inventory `outputs/hermes-reviewed-candidate-worktrees.json`. No product code changed to assemble the candidate.

Job2's tiered-root adoption, history-compatible replay drop and other reviewed upstream prerequisites remain held; its queue claim/ledger/table are unchanged by this receipt. Job3 must follow completion of the console and capability waves. No upstream merge, full suite, architecture/broad gate or main landing. Claude owns full validation; user owns landing. Ready for parent review.
