# Configuration

`hutches/tmo.toml` contains the non-secret TMO defaults, also packaged for use
outside the checkout. `report --hutch tmo` uses that profile; `--config` overrides
it with a custom file. Python 3.11+ parses TOML without an extra dependency.

Required fields: `hutch`, `timezone`, and `model`. Optional fields:
`provider_config`, `opencode`, `output_root`, `log_root`, and the pinned
`daq_skills` table. A legacy numeric `partition` field is accepted but does not
filter or divide reports. Platform values from source logs remain metadata.

Configuration does not establish model entitlement or source access. Credentials
remain external references in the provider configuration. Keep private overrides
outside the repository or in ignored `config/local/`; never commit credential
values. CLI options override corresponding profile fields.
