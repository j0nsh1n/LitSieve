"""Named action: list_files."""
import sys

from app.operator.actions import cmd_list_files

if __name__ == "__main__":
    raise SystemExit(cmd_list_files(sys.argv[1:]))
