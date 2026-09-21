"""Read-only, loopback-only browser access to one completed analysis."""

from dataclasses import dataclass, replace
from datetime import datetime
import getpass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import tempfile
import tomllib
from urllib.parse import urlsplit

from .collectors.logs import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .html_reports import CSP, html_bundle
from .reports import render_report, validate_findings


@dataclass(frozen=True)
class ViewerSettings:
    output_root: str = "~/daq/agent-logs"
    port: int = 8765
    ssh_host: str | None = None


@dataclass
class Report:
    directory: Path
    manifest: dict
    findings: dict
    evidence: dict[str, str]
    raw_evidence: dict[str, bytes]


def personal_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "daq-agent" / "viewer.toml"


def validate_settings(settings: ViewerSettings) -> ViewerSettings:
    if not isinstance(settings.output_root, str) or not settings.output_root.strip():
        raise ValueError("viewer output_root must be a nonempty path")
    if type(settings.port) is not int or not 0 <= settings.port <= 65535:
        raise ValueError("viewer port must be between 0 and 65535 (0 selects an available port)")
    if settings.ssh_host is not None and (
        not isinstance(settings.ssh_host, str)
        or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", settings.ssh_host)
    ):
        raise ValueError("ssh_host must be an SSH alias or [user@]hostname")
    return settings


def load_viewer_settings(path: Path | None = None) -> ViewerSettings:
    target = path.expanduser() if path else personal_config_path()
    if path is None and not target.exists():
        return ViewerSettings()
    with target.open("rb") as stream:
        data = tomllib.load(stream)
    if set(data) - {"output_root", "port", "ssh_host"}:
        raise ValueError("viewer settings allow only output_root, port, and ssh_host")
    return validate_settings(ViewerSettings(**data))


def save_viewer_settings(settings: ViewerSettings, path: Path | None = None) -> Path:
    validate_settings(settings)
    target = path.expanduser() if path else personal_config_path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = (f'output_root = {json.dumps(settings.output_root, ensure_ascii=False)}\n'
               f'port = {settings.port}\n')
    if settings.ssh_host:
        content += f'ssh_host = {json.dumps(settings.ssh_host)}\n'
    # Replace atomically; preserve unrelated files in the personal config directory.
    fd, temporary = tempfile.mkstemp(prefix=".viewer-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def read_artifact(directory: Path, name: str, limit: int) -> bytes:
    path = directory / name
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(directory) or not resolved.is_file():
        raise ValueError(f"artifact is not a file within the run directory: {name}")
    with resolved.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"artifact is too large: {name}")
    return content


def read_manifest(directory: Path) -> dict:
    manifest = json.loads(read_artifact(directory, "manifest.json", 128 * 1024))
    if not isinstance(manifest, dict) or manifest.get("status") != "completed":
        raise ValueError("run is not a completed report")
    if manifest.get("workflow") != "analyze-logs" or manifest.get("schema_version") != 1:
        raise ValueError("unsupported report workflow or schema")
    return manifest


def report_time(manifest: dict) -> datetime:
    value = manifest.get("completed_at", manifest.get("created_at"))
    if not isinstance(value, str):
        raise ValueError("report must have a timestamp")
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        raise ValueError("report timestamp must include a UTC offset")
    return timestamp


def load_report(directory: Path) -> Report:
    directory = directory.expanduser().resolve(strict=True)
    try:
        manifest = read_manifest(directory)
        report_time(manifest)
        settings = manifest["settings"]
        if not re.fullmatch(r"[a-z]{3}", settings["hutch"]):
            raise ValueError("invalid report hutch")
        if type(settings["partition"]) is not int or not 0 <= settings["partition"] <= 7:
            raise ValueError("invalid report partition")
        for value in (settings["model"], manifest["created_at"], manifest["evidence_kind"],
                      manifest["window"]["start_inclusive"], manifest["window"]["end_exclusive"]):
            if not isinstance(value, str):
                raise ValueError("invalid report metadata")
        sources = manifest["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 8:
            raise ValueError("report must contain 1–8 sources")
        raw, evidence, total = {}, {}, 0
        for source in sources:
            source_id = source["id"]
            if not re.fullmatch(r"log-[1-8]", source_id) or source_id in evidence:
                raise ValueError("invalid or duplicate source ID")
            if source["snapshot"] != f"evidence/{source_id}.txt":
                raise ValueError("invalid evidence snapshot path")
            if not isinstance(source["original_path"], str):
                raise ValueError("invalid original source path")
            content = read_artifact(directory, source["snapshot"], MAX_FILE_BYTES)
            total += len(content)
            text = content.decode("utf-8")
            if not text.strip() or "\x00" in text or total > MAX_TOTAL_BYTES:
                raise ValueError("invalid or oversized evidence")
            if (source["sha256"] != hashlib.sha256(content).hexdigest()
                    or type(source["bytes"]) is not int or source["bytes"] != len(content)
                    or type(source["lines"]) is not int or source["lines"] != len(text.splitlines())):
                raise ValueError(f"evidence integrity check failed: {source_id}")
            raw[source_id], evidence[source_id] = content, text
        findings = validate_findings(read_artifact(directory, "findings.json", 3 * 1024 * 1024).decode(), sources)
        return Report(directory, manifest, findings, evidence, raw)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"invalid report metadata in {directory}") from error


def latest_report(root: Path, hutch: str | None = None) -> Report:
    root = root.expanduser().resolve()
    if hutch is not None and not re.fullmatch(r"[a-z]{3}", hutch):
        raise ValueError("hutch must be a lowercase three-letter code")
    candidates = []
    # Current hutch/year/month/run layout plus the earlier year/month/run layout.
    for pattern in ("*/*/*/*/manifest.json", "*/*/*/manifest.json"):
        for path in root.glob(pattern):
            try:
                directory = path.parent.resolve(strict=True)
                if not directory.is_relative_to(root):
                    continue
                manifest = read_manifest(directory)
                if hutch is None or manifest.get("settings", {}).get("hutch") == hutch:
                    candidates.append((report_time(manifest), str(directory), directory))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    for _, _, directory in sorted(candidates, reverse=True):
        try:
            return load_report(directory)
        except (OSError, ValueError):
            continue
    raise ValueError(f"no valid completed reports found under {root}; run analyze-logs first "
                     "or supply an explicit run directory")


def report_assets(report: Report) -> dict[str, tuple[bytes, str]]:
    assets = {name: (content, "text/html; charset=utf-8")
              for name, content in html_bundle(report.findings, report.manifest, report.evidence).items()}
    assets["report.md"] = (render_report(report.findings, report.manifest).encode(), "text/plain; charset=utf-8")
    for name, value in (("findings.json", report.findings), ("manifest.json", report.manifest)):
        assets[name] = ((json.dumps(value, indent=2) + "\n").encode(), "application/json")
    for source in report.manifest["sources"]:
        assets[source["snapshot"]] = (report.raw_evidence[source["id"]], "text/plain; charset=utf-8")
    return assets


def make_server(report: Report, port: int) -> tuple[ThreadingHTTPServer, str]:
    assets = report_assets(report)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(send_body=True)

        def do_HEAD(self):
            self.respond(send_body=False)

        def respond(self, *, send_body):
            parts = urlsplit(self.path).path.split("/", 2)
            valid = len(parts) == 3 and secrets.compare_digest(parts[1].encode(), token.encode())
            resource = parts[2] if valid else ""
            payload = assets.get(resource)
            status = 200 if payload is not None else 404
            content, content_type = payload or (b"Not found\n", "text/plain; charset=utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP + "; frame-ancestors 'none'")
            if status == 200 and not resource.endswith(".html"):
                self.send_header("Content-Disposition", f'attachment; filename="{Path(resource).name}"')
            self.end_headers()
            if send_body:
                self.wfile.write(content)

        def log_message(self, format, *args):
            # Avoid recording token-bearing URLs or evidence in access logs.
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server, token


def viewing_instructions(report: Report, port: int, token: str, ssh_host: str | None) -> str:
    hostname = socket.gethostname()
    destination = ssh_host or f"{getpass.getuser()}@{hostname}"
    command = shlex.join(["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-L",
                          f"127.0.0.1:{port}:127.0.0.1:{port}", destination])
    url = f"http://127.0.0.1:{port}/{token}/report.html"
    message = (f"Viewing completed report\nHutch: {report.manifest['settings']['hutch']}\n"
               f"Run: {report.directory}\nViewer host: {hostname}\nViewer port: {port}\n\n"
               f"From a laptop:\n1. In a LOCAL terminal, run this and leave it running:\n   {command}\n\n"
               f"2. Open this URL in your LOCAL browser:\n   {url}\n\n"
               "Using NoMachine with a browser on this host?\n"
               "Open the URL above directly; no SSH tunnel is needed.\n\n")
    if ssh_host:
        message += f"The SSH alias {ssh_host!r} must reach {hostname}; your laptop's SSH config handles jump hosts.\n"
    else:
        message += ("Using a jump host or laptop SSH alias? Restart with --ssh-host YOUR_ALIAS.\n"
                    "Add --save-settings to remember it for future invocations.\n")
    return message + "Keep this viewer running while browsing. Press Ctrl+C here to stop it."


def view_report(args) -> int:
    settings = load_viewer_settings(args.viewer_config)
    overrides = {key: value for key, value in {
        "output_root": str(args.root) if args.root is not None else None,
        "port": args.port, "ssh_host": args.ssh_host,
    }.items() if value is not None}
    settings = validate_settings(replace(settings, **overrides))
    report = load_report(args.run) if args.run else latest_report(Path(settings.output_root), args.hutch)
    if args.hutch and report.manifest["settings"]["hutch"] != args.hutch:
        raise ValueError("selected report does not match --hutch")
    try:
        server, token = make_server(report, settings.port)
    except OSError as error:
        raise OSError(f"could not start viewer on 127.0.0.1:{settings.port}; "
                      f"try --port with another port ({error.strerror})") from error
    with server:
        if args.save_settings:
            saved = save_viewer_settings(settings, args.viewer_config)
            print(f"Saved personal viewer settings: {saved}")
        print(viewing_instructions(report, server.server_port, token, settings.ssh_host), flush=True)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            print("\nViewer stopped.")
    return 0
