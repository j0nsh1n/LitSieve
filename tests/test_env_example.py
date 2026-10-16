"""Every setting the code reads has a line in .env.example (audit 23.4)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ = re.compile(
    r"""(?:getenv|environ\.get|_env|_env_truthy|env_flag|environ\[)\(?\s*["']([A-Z][A-Z0-9_]{2,})["']"""
)
NOT_SETTINGS = {"PATH"}


def test_env_example_lists_every_setting_the_code_reads():
    names = set()
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "tools").glob("*.py")):
        names.update(READ.findall(path.read_text(encoding="utf-8")))
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    missing = sorted(n for n in names - NOT_SETTINGS if n not in example)
    assert not missing, f".env.example has no line for {missing}"
