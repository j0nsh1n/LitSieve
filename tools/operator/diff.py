"""Named action: diff."""
import sys

from app.operator.actions import cmd_diff

if __name__ == "__main__":
    raise SystemExit(cmd_diff(sys.argv[1:]))
