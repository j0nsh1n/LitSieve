"""Operator action JSON must parse before secret redaction."""

import json

from app.operator.runner import decode_action_payload


def test_read_file_content_keeps_token_assignment():
    """Redacting stdout before json.loads ate `token = …` inside source.

    The editor would then save the redacted text back to disk.
    """
    content = "token = make_token()\nprint(token)\n"
    stdout = json.dumps({"ok": True, "path": "app/example.py", "content": content})
    payload = decode_action_payload(stdout, "", 0, "read_file")
    assert payload["ok"] is True
    assert payload["content"] == content
    assert "make_token()" in payload["content"]


def test_parse_failure_is_never_ok_on_exit_zero():
    payload = decode_action_payload("not-json token = make_token()", "boom", 0, "read_file")
    assert payload["ok"] is False
    assert "JSON" in payload["detail"]


def test_diagnostic_fields_redact_secrets_content_does_not():
    content = "SECRET_KEY=keep-this-in-source\n"
    stdout = json.dumps({
        "ok": True,
        "content": content,
        "detail": "SECRET_KEY=leaked-in-log",
    })
    payload = decode_action_payload(stdout, "", 0, "read_file")
    assert payload["content"] == content
    assert "leaked-in-log" not in payload["detail"]
    assert "keep-this-in-source" in payload["content"]
