"""Small helpers shared by both entry points."""

import datetime
import re
import sys


class Failure(Exception):
    """A user-facing error: the script prints it and exits."""

    def __init__(self, errors, exit_code=2, header=None):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        self.exit_code = exit_code
        self.header = header
        super().__init__("; ".join(self.errors))


def die(failure):
    """Print a Failure to stderr and exit with its code."""
    if failure.header:
        print(failure.header, file=sys.stderr)
    if len(failure.errors) == 1 and not failure.header:
        print("error: " + failure.errors[0], file=sys.stderr)
    else:
        for e in failure.errors:
            print("  - " + e, file=sys.stderr)
    sys.exit(failure.exit_code)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shell_quote(s):
    return s if re.match(r"^[A-Za-z0-9_./:=@%+-]+$", s) else "'" + s.replace("'", "'\\''") + "'"


def read_stdin_body(what="body"):
    """The text piped on stdin, stripped. Raises Failure when stdin is a terminal or empty."""
    if sys.stdin.isatty():
        raise Failure("no %s on stdin: pipe it with a quoted heredoc (<<'EOF')" % what)
    text = sys.stdin.read().strip()
    if not text:
        raise Failure("empty %s on stdin" % what)
    return text
