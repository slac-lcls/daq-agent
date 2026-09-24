"""Read-only, loopback-only browser access to one completed analysis."""

from dataclasses import dataclass, replace
import getpass
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

from .report_store import Report, read_artifact, read_manifest, report_time, load_report, latest_report
from .html_reports import CSP, html_bundle
from .reports import render_report


@dataclass(frozen=True)
class ViewerSettings:
    output_root: str = "~/daq/agent-logs"
    port: int = 8765
    ssh_host: str | None = None


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
