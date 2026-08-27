"""Named action: read_file."""
import sys

from app.operator.actions import cmd_read_file

if __name__ == "__main__":
    raise SystemExit(cmd_read_file(sys.argv[1:]))
