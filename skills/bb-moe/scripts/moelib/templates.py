"""Fixed texts as template files (ADR 0003).

One `.md` file per message under `<skill>/templates/<group>/`, rendered with
`string.Template` (`${name}`). A literal `$` in a template is written `$$`. There
is no logic in a template: a variant is its own file and the caller picks it.

Before rendering, the template's identifiers are compared with the variables the
caller supplies. A missing or unused variable raises `TemplateError` naming the
file and the variables, so nothing is written or sent.
"""

import os
import string

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "templates"
)

# Every template rendered in this process, "group/name": for the tests' coverage check.
RENDERED = set()


class TemplateError(Exception):
    pass


def template_path(ref, root=None):
    return os.path.join(root or TEMPLATE_DIR, *ref.split("/")) + ".md"


def all_refs(root=None):
    """Every template file as "group/name", sorted."""
    base = root or TEMPLATE_DIR
    refs = []
    for group in sorted(os.listdir(base)):
        folder = os.path.join(base, group)
        if os.path.isdir(folder):
            refs += ["%s/%s" % (group, f[:-3]) for f in sorted(os.listdir(folder)) if f.endswith(".md")]
    return refs


def identifiers(ref, root=None):
    return set(string.Template(_load(ref, root)).get_identifiers())


def render(ref, root=None, **variables):
    """Render template `ref` ("group/name") with `variables`; text without a trailing newline."""
    path = template_path(ref, root)
    template = string.Template(_load(ref, root))
    if not template.is_valid():
        raise TemplateError("%s: invalid placeholder; write a literal $ as $$" % path)
    needed = set(template.get_identifiers())
    given = set(variables)
    missing, unused = sorted(needed - given), sorted(given - needed)
    if missing or unused:
        parts = []
        if missing:
            parts.append("missing variable%s %s" % ("s" if len(missing) > 1 else "", ", ".join(missing)))
        if unused:
            parts.append("unused variable%s %s" % ("s" if len(unused) > 1 else "", ", ".join(unused)))
        raise TemplateError("%s: %s" % (path, "; ".join(parts)))
    RENDERED.add(ref)
    return template.substitute(variables)


def _load(ref, root=None):
    path = template_path(ref, root)
    try:
        with open(path) as f:
            text = f.read()
    except OSError as e:
        raise TemplateError("%s: cannot read template (%s)" % (path, e.strerror or e))
    return text[:-1] if text.endswith("\n") else text
