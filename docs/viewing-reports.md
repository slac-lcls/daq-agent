# View a completed report

Status: implemented. `daq-agent view` opens a local HTTP viewer for one completed
log-analysis run. It uses saved findings and evidence, with no model calls,
OpenCode process, or live DAQ access.

## Quick start

Activate the project virtual environment, then run:

```bash
daq-agent view
```

The viewer searches `~/daq/agent-logs/<hutch>/YYYY/MM/<run>/` for the most recent
valid completed report across hutches. It orders reports by `completed_at`, falling
back to `created_at` for older runs. Failed, preparation-only, incomplete, and
invalid runs are skipped. The older layout without the hutch directory is also
supported. Selection does not use filesystem modification times.

The viewer prints the selected hutch, run directory, actual serving hostname,
port, SSH tunnel command, and full browser URL. It stays in the foreground;
press Ctrl+C to stop it. A browser is not opened automatically on a remote host.

Useful overrides:

```bash
daq-agent view --hutch tmo
daq-agent view /path/to/completed/run
daq-agent view --root /another/report/tree
daq-agent view --port 8766
```

The default port is 8765. An occupied port produces an error with instructions
to choose another; `--port 0` selects an available remote port and prints it.
If the matching port is occupied on the laptop, choose another viewer port and
use the newly printed tunnel command and URL.

## SSH and jump hosts

Use the SSH alias that works on your laptop and reaches the machine running the
viewer. For example, when the laptop alias `sdfiana` reaches `sdfiana025` through
a configured `ProxyJump`:

```bash
daq-agent view --ssh-host sdfiana --save-settings
```

This saves the alias and viewer defaults on the remote account. Future invocations
can use just `daq-agent view`.

On the laptop, copy the command printed by the viewer, for example:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8765:127.0.0.1:8765 sdfiana
```

Leave that local terminal running and open the full printed URL in the laptop's
browser. The URL contains a temporary access token and changes each time the
viewer starts. Keep both the viewer and tunnel running while browsing.

SSH reads the laptop's configuration and handles the jump host(s). The viewer
does not inspect or change laptop SSH settings. It cannot determine whether an
alias points to the correct server; compare the printed serving hostname with
the alias's destination. Without an alias, the printed command uses the current
remote username and hostname and includes a reminder about `--ssh-host`.

With NoMachine, if the browser and viewer run on the same host, open the printed
URL directly without a tunnel. A browser on a different NoMachine host still
needs a connection to the serving host.

## Personal settings

Settings are read from `$XDG_CONFIG_HOME/daq-agent/viewer.toml`, or
`~/.config/daq-agent/viewer.toml` when `XDG_CONFIG_HOME` is unset:

```toml
output_root = "~/daq/agent-logs"
port = 8765
ssh_host = "sdfiana"
```

Command-line values take precedence. `--save-settings` writes the effective root,
port, and alias to this private file; it does not save the access token, hutch
filter, or selected run. `--viewer-config /path/to/settings.toml` selects an
existing alternative personal configuration file. SSH aliases are personal
preferences, not shared hutch configuration. A custom analysis `output_root`
must also be supplied to the viewer through `--root` or these personal settings.

## Report and evidence presentation

The viewer builds HTML from `findings.json` and `manifest.json`, using the same
structured content as `report.md`. It does not interpret arbitrary Markdown or
execute model-generated HTML. Report text and log contents are HTML-escaped.

Each citation opens a log page in a new tab/window according to browser settings,
scrolls to the first cited line, and highlights the cited range. Log pages show
the original source path and snapshot hash and provide a raw-text download.
Line numbers refer to the retained excerpt, not a larger original DAQ log.
Snapshot hashes, byte counts, line counts, and citation bounds are checked before
serving. The viewer does not establish the semantic correctness of findings.

New analyses also save `report.html` and `logs/log-N.html` alongside the existing
Markdown, JSON, and raw evidence. Copy the complete run directory to view these
files offline; relative links remain valid. Existing runs are rendered in memory
by `view` without modifying their saved artifacts. No network fonts, scripts, or
other external assets are needed by the HTML pages.

## Access boundary

The viewer listens only on `127.0.0.1` and requires its random URL token for every
resource. It serves an explicit set of report, manifest, findings, and evidence
assets, with no directory browsing or arbitrary file access. Runtime event logs,
stderr, and provider credentials are not served. Token-bearing requests are not
logged; responses disable caching and referrer transmission.

Treat the URL as access to that report. This is a personal, temporary viewer;
shared publishing and multi-user hosting require a separate deployment design.

New `report` runs produce one hutch/window report directly in the printed output
directory. Large reports combine findings from bounded model sessions and keep
citations linked to the root evidence snapshots. Internal `batches/NNN/` sessions
are excluded from automatic latest-report selection, including when a later batch
fails. Earlier per-partition batch reports remain discoverable and can be
viewed explicitly. Prepared-only and failed reports are excluded.
