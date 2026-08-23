"""Named action: ask_grok. Prompt is one argv element; no shell interpolation."""
import sys

from app.operator.actions import cmd_ask_grok

if __name__ == "__main__":
    raise SystemExit(cmd_ask_grok(sys.argv[1:]))
