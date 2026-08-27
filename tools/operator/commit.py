"""Named action: commit."""
import sys

from app.operator.actions import cmd_commit

if __name__ == "__main__":
    raise SystemExit(cmd_commit(sys.argv[1:]))
