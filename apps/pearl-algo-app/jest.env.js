// Pin TZ to UTC so Intl-based formatters produce deterministic output in CI.
// Loaded via `setupFiles` (runs before the test framework and before any
// Date/Intl internals are cached), so tests like `formatTime(...)` that assert
// exact strings don't drift across the host's local timezone.
process.env.TZ = 'UTC'
