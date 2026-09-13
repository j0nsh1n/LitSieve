"""Security contract for files that may enter the Docker build context."""

import json
import shlex
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
APPROVED_COPY_SOURCES = {
    "requirements.txt",
    "app",
    "templates",
    "static",
    "tools/operator",
}
APPROVED_CONTEXT_RULES = {
    "requirements.txt",
    "app",
    "app/**",
    "templates",
    "templates/**",
    "static",
    "static/**",
    "tools",
    "tools/operator",
    "tools/operator/**",
}
REQUIRED_FINAL_EXCLUSIONS = {
    "**/.env",
    "**/.env.*",
    "**/.secret_key",
    "**/*.secret_key",
    "**/secrets",
    "**/secrets/**",
    "**/*.pem",
    "**/*.key",
    "**/*.pfx",
    "**/*.p12",
    "**/*.crt",
    "**/mailersend-*.txt",
    "**/*smtp*secret*",
    "**/*smtp*credentials*",
    "**/ai_settings.json",
    "**/*.db",
    "**/*.db-wal",
    "**/*.db-shm",
    "**/*.db-*",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/user_data",
    "**/user_data/**",
    "**/dev_data",
    "**/dev_data/**",
    "**/backups",
    "**/backups/**",
    "**/*.tar.gz",
    "**/*.tar.zst",
    "**/*.zip",
    "**/logs",
    "**/logs/**",
    "**/venv",
    "**/venv/**",
    "**/.venv",
    "**/.venv/**",
    "**/*.log",
    "**/__pycache__",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/*.pyo",
}


def _dockerfile_instructions() -> list[str]:
    logical: list[str] = []
    current = ""
    for raw in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        current = f"{current} {line}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        logical.append(current)
        current = ""
    assert not current, "Dockerfile ends with an unfinished instruction"
    return logical


def _copy_sources(payload: str) -> list[str]:
    fields = json.loads(payload) if payload.startswith("[") else shlex.split(payload)
    while fields and fields[0].startswith("--"):
        fields.pop(0)
    assert len(fields) >= 2, f"Malformed COPY instruction: {payload}"
    return fields[:-1]


def test_dockerfile_copies_only_approved_runtime_sources():
    sources: set[str] = set()
    for instruction in _dockerfile_instructions():
        keyword, _, payload = instruction.partition(" ")
        keyword = keyword.upper()
        assert keyword != "ADD", "ADD can introduce unreviewed local or remote content"
        if keyword != "COPY":
            continue
        if any(part.startswith("--from=") for part in shlex.split(payload)):
            continue
        for source in _copy_sources(payload):
            normalized = source.rstrip("/")
            path = PurePosixPath(normalized)
            assert normalized not in {"", "."}
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert not any(char in source for char in "*?[")
            sources.add(normalized)

    assert sources == APPROVED_COPY_SOURCES


def test_docker_context_defaults_to_deny_all_with_explicit_runtime_allowlist():
    rules = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert rules[0] == "**", "The build context must deny files by default"
    negation_indexes = [i for i, rule in enumerate(rules) if rule.startswith("!")]
    assert negation_indexes
    last_negation = max(negation_indexes)
    allowed = {rule[1:].rstrip("/") for rule in rules if rule.startswith("!")}
    assert allowed == APPROVED_CONTEXT_RULES
    final_exclusions = set(rules[last_negation + 1 :])
    assert REQUIRED_FINAL_EXCLUSIONS <= final_exclusions
    assert all(not rule.startswith("!") for rule in rules[last_negation + 1 :])
