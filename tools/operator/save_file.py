"""Named action: save_file. Content is read from stdin, never from a shell string."""
import sys

from app.operator.actions import cmd_save_file

if __name__ == "__main__":
    raise SystemExit(cmd_save_file(sys.argv[1:]))
