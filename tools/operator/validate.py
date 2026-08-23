"""Named action: validate."""
import sys

from app.operator.actions import cmd_validate

if __name__ == "__main__":
    raise SystemExit(cmd_validate(sys.argv[1:]))
