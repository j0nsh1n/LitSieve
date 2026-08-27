"""Named action: deploy."""
import sys

from app.operator.actions import cmd_deploy

if __name__ == "__main__":
    raise SystemExit(cmd_deploy(sys.argv[1:]))
