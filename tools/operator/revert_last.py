"""Named action: revert_last."""
import sys

from app.operator.actions import cmd_revert_last

if __name__ == "__main__":
    raise SystemExit(cmd_revert_last(sys.argv[1:]))
