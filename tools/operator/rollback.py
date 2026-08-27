"""Named action: rollback."""
import sys

from app.operator.actions import cmd_rollback

if __name__ == "__main__":
    raise SystemExit(cmd_rollback(sys.argv[1:]))
