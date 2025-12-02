import warnings

# Suppress noisy deprecation warning from eventkit about missing event loop during tests.
warnings.filterwarnings(
    "ignore", message="There is no current event loop", category=DeprecationWarning
)
