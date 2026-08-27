"""Named action: grok_status."""
import sys

from app.operator.actions import cmd_grok_status

if __name__ == "__main__":
    raise SystemExit(cmd_grok_status(sys.argv[1:]))
