# Configuration

`hutches/tmo.toml` is the initial non-secret configuration. Pass its path explicitly
with `--config`; the scaffold does not discover credentials or merge user-global
OpenCode settings. TOML is used so Python 3.11+ can parse it without dependencies.

The current parser accepts only hutch, partition, timezone, and model. These
values scope a plan; they do not validate a model entitlement or source access.
Confirm partition selection before implementing a real investigation.

Future source endpoints, read limits, credential references, runtime configuration,
and output locations need a reviewed schema extension. Keep site-private overrides
outside the repository, or in ignored `config/local/` while developing. Never put
credential values in a hutch configuration.
