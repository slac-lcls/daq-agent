"""Explicit synchronization and offline verification of pinned diagnostic skills."""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_FILES = 100
SUITE_FILES = frozenset({"README.md"})


def valid_snapshot_path(name: str, skills) -> bool:
    relative = PurePosixPath(name)
    return (not relative.is_absolute() and str(relative) == name
            and not any(part in {"", ".", ".."} for part in name.split("/"))
            and (name in SUITE_FILES or (len(relative.parts) >= 2 and relative.parts[0] in skills)))


@dataclass(frozen=True)
class SkillSource:
    repository: str
    branch: str
    revision: str
    directory: str
    skills: tuple[str, ...] = ("psana-daq", "psana-daq-logs")


def parse_source(data: dict) -> SkillSource:
    if not isinstance(data, dict) or set(data) - {"repository", "branch", "revision", "directory", "skills"}:
        raise ValueError("invalid daq_skills configuration")
    try:
        source = SkillSource(**data)
    except TypeError as error:
        raise ValueError("daq_skills requires repository, branch, revision, and directory") from error
    # HTTPS only: no local paths, credentials, git remote helpers, or transport options.
    if not isinstance(source.repository, str) or not re.fullmatch(
            r"https://[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source.repository):
        raise ValueError("skill repository must be an HTTPS repository URL without credentials")
    if not isinstance(source.revision, str) or not re.fullmatch(r"[0-9a-f]{40}", source.revision):
        raise ValueError("skill revision must be a full 40-character commit SHA")
    if not isinstance(source.branch, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", source.branch):
        raise ValueError("skill branch must be a branch name")
    if (not isinstance(source.directory, str) or not source.directory
            or any(part in {"", ".", ".."} for part in source.directory.split("/"))
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", source.directory)):
        raise ValueError("skill directory must be a relative repository path")
    names = source.skills
    if (not isinstance(names, (list, tuple)) or not 1 <= len(names) <= 8
            or any(not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                   or name == "log-triage" for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("skills must be distinct skill names (excluding reserved log-triage)")
    return SkillSource(source.repository, source.branch, source.revision, source.directory, tuple(names))


def descriptor(source: SkillSource) -> dict:
    return json.loads(json.dumps(asdict(source)))


def cache_directory(source: SkillSource, root: Path | None = None) -> Path:
    if root is None:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "daq-agent/skills"
    key = hashlib.sha256(json.dumps(descriptor(source), sort_keys=True).encode()).hexdigest()
    return root.expanduser() / key


def validate_skill(name: str, content: bytes) -> None:
    """Validate the simple frontmatter used by the pinned upstream suite."""
    text = content.decode("utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError(f"missing skill frontmatter: {name}")
    fields = {}
    for line in lines[1:lines[1:].index("---") + 1]:
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    if fields.get("name") != name or not fields.get("description"):
        raise ValueError(f"skill frontmatter name/description mismatch: {name}")


def read_snapshot(directory: Path, source: SkillSource) -> tuple[dict, dict[str, bytes]]:
    """Verify bytes before use; analysis never fetches or imports upstream code."""
    try:
        if directory.is_symlink():
            raise ValueError("skill cache must not be a symlink")
        metadata = json.loads((directory / "manifest.json").read_text())
        if metadata["source"] != descriptor(source) or metadata["schema_version"] != 1:
            raise ValueError("skill cache provenance mismatch")
        records = metadata["files"]
        if not isinstance(records, dict) or not 1 <= len(records) <= MAX_FILES:
            raise ValueError("invalid skill cache inventory")
        contents, total = {}, 0
        for name, record in records.items():
            if not valid_snapshot_path(name, source.skills):
                raise ValueError("invalid skill cache path")
            path = directory / name
            if any(parent.is_symlink() for parent in (path, *path.parents) if parent != directory.parent):
                raise ValueError("symlink in skill cache")
            with path.open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
            total += len(content)
            if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("skill cache exceeds size limits")
            if record != {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}:
                raise ValueError("skill cache integrity check failed")
            contents[name] = content
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
        if actual != set(contents) | {"manifest.json"}:
            raise ValueError("unexpected files in skill cache")
        for name in source.skills:
            validate_skill(name, contents[f"{name}/SKILL.md"])
        return metadata, contents
    except (OSError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("skill cache is missing or invalid; run daq-agent sync-skills --config CONFIG") from error


def sync_skills(source: SkillSource, root: Path | None = None) -> Path:
    target = cache_directory(source, root)
    if target.exists():
        read_snapshot(target, source)
        return target
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sync-", dir=target.parent) as temp:
        temporary = Path(temp)
        repository, snapshot = temporary / "git", temporary / "snapshot"
        snapshot.mkdir(mode=0o700)
        # No checkout, submodule operations, hooks, or execution of downloaded helpers.
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")

        def git(*args):
            result = subprocess.run(["git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
                                     "-C", str(repository), *args], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            if result.returncode:
                raise ValueError("could not fetch/read pinned skill revision; check repository access and commit")
            return result.stdout

        repository.mkdir()
        git("init", "--quiet")
        git("fetch", "--quiet", "--depth=1", source.repository, source.revision)
        if git("rev-parse", "FETCH_HEAD^{commit}").decode().strip() != source.revision:
            raise ValueError("fetched revision does not match configured commit")
        records, total = {}, 0
        # Include the optional suite overview referenced by selected skills.
        paths = [f"{name}/" for name in source.skills] + sorted(SUITE_FILES)
        for name in paths:
            prefix = f"{source.directory}/{name}"
            entries = git("ls-tree", "-r", "-z", "--full-tree", source.revision, "--", prefix)
            for entry in entries.split(b"\x00"):
                if not entry:
                    continue
                header, raw_path = entry.split(b"\t", 1)
                mode, kind, object_id = header.decode().split()
                path = raw_path.decode()
                if not path.startswith(prefix) or mode not in {"100644", "100755"} or kind != "blob":
                    raise ValueError("skills must contain regular files, not symlinks or submodules")
                size = int(git("cat-file", "-s", object_id))
                total += size
                if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(records) >= MAX_FILES:
                    raise ValueError("upstream skills exceed size limits")
                content = git("cat-file", "blob", object_id)
                relative = path[len(source.directory) + 1:]
                if not valid_snapshot_path(relative, source.skills):
                    raise ValueError("unsafe upstream skill path")
                destination = snapshot / relative
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                destination.write_bytes(content)
                destination.chmod(0o600)
                records[relative] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        metadata = {"schema_version": 1, "source": descriptor(source), "files": records}
        (snapshot / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        (snapshot / "manifest.json").chmod(0o600)
        read_snapshot(snapshot, source)
        try:
            snapshot.rename(target)
        except FileExistsError:
            read_snapshot(target, source)
    return target


def retain_skills(source: SkillSource, output: Path, root: Path | None = None) -> dict:
    metadata, contents = read_snapshot(cache_directory(source, root), source)
    for name, content in contents.items():
        destination = output / "upstream-skills" / name
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.write_bytes(content)
        destination.chmod(0o600)
    return {"status": "loaded_from_cache", **metadata}
