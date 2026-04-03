# USER.md

Learned working preferences for this repo's maintainer.

## Preferences

- Flag repetition aggressively.
  Why: duplicated docs, config, and code drift out of sync quickly in this repo.
- Prioritize well-tested changes.
  Why: untested work is not considered complete.
- Prefer right-sized solutions.
  Why: under-engineering hides edge cases and over-engineering makes live systems harder to operate.
- Handle edge cases explicitly.
  Why: silent skips and swallowed failures are dangerous in trading infrastructure.
- Prefer explicit code over clever code.
  Why: readability matters more than terseness during incident response.
- Default to conservative cleanup: keep > archive > delete.
  Why: historical context can matter for audits and rollback work.
- Never hallucinate repo facts.
  Why: invented paths, function names, or APIs cause compounding operational mistakes.
- Clean workspace artifacts as work progresses.
  Why: the maintainer prefers ongoing hygiene rather than separate cleanup passes.
