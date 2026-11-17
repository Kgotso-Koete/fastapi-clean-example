"""
Counts the tests that prove each user story (agents.md, section 6.1).

A test names the user story it proves with the `story` marker, registered in
pyproject.toml, for example `@pytest.mark.story("ORG.D2.US.J3.A2")` on a test or a
class, or `pytestmark = pytest.mark.story(...)` at the top of a file. The stories
themselves live in docs/plans/user-stories/, one file per feature.

At the end of every run, this file prints a "User stories" section with one line per
story: how many of its tests passed, out of how many ran, by kind of test, such as
`ORG.D2.US.J3.A2: 6/6 (BU), 5/5 (BI)`. Those lines are where a stories file's "Tests
passing" column comes from: counted from a real run, never typed by hand.

This is test-support code (agents.md, section 2.1): it changes no test's behaviour,
it only reports, so it has no tests of its own.
"""

import re
from collections import defaultdict

import pytest

# The shape of a story ID: feature code, domain, actor, journey, action. A typo in a
# marker stops the run here, instead of printing a line for a story that doesn't exist.
_STORY_ID = re.compile(r"^[A-Z]+\.D\d+\.[A-Z]{2}\.J\d+\.A\d+$")

# The kinds of test, told apart by the folder a test lives in, in the order they're
# printed. The labels match the stories files' "Tests passing" column: B for this
# backend repo (a frontend repo adds FU, FI and FE for its own unit, integration and
# end-to-end tests), then BU unit, BI integration, BS sanity, BSm smoke.
_KIND_BY_FOLDER = (("/unit/", "BU"), ("/integration/", "BI"), ("/sanity/", "BS"), ("/smoke/", "BSm"))
_KIND_ORDER = tuple(kind for _, kind in _KIND_BY_FOLDER)

# What collection found: each test's stories and kind, by its pytest node id.
_stories_by_test: dict[str, tuple[tuple[str, ...], str]] = {}

# How each test ended, by node id: "passed" or "failed". A skipped test never ran,
# so it's never recorded, and doesn't count.
_outcome_by_test: dict[str, str] = {}


def _kind_of(path: str) -> str | None:
    """Say which kind of test lives at this path, or None for a folder with no kind."""
    for folder, kind in _KIND_BY_FOLDER:
        if folder in path:
            return kind
    return None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Record every collected test's stories and kind, checking each story ID's shape."""
    for item in items:
        # iter_markers() also finds a marker set on the test's class or module.
        stories = tuple(str(mark.args[0]) for mark in item.iter_markers("story"))
        for story in stories:
            if not _STORY_ID.match(story):
                msg = f"{item.nodeid}: story ID {story!r} doesn't look like ORG.D2.US.J3.A2"
                raise pytest.UsageError(msg)
        kind = _kind_of(item.path.as_posix())
        if kind is None:
            # A characterisation or migration test pins the whole app, not one story;
            # one that names a story would be counted under no kind, so refuse it.
            if stories:
                msg = f"{item.nodeid}: a test naming a story must live in a unit, integration, sanity or smoke folder"
                raise pytest.UsageError(msg)
            kind = "-"
        _stories_by_test[item.nodeid] = (stories, kind)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Note how each test ended: failing in any phase (setup, call, teardown) wins."""
    if report.failed:
        _outcome_by_test[report.nodeid] = "failed"
    elif report.when == "call" and report.passed:
        _outcome_by_test.setdefault(report.nodeid, "passed")


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print each story's passed/run counts by kind, sorted by story ID."""
    # passed[story][kind] and run[story][kind], counted from the tests that ran.
    passed: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    run: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    untagged = 0
    for nodeid, outcome in _outcome_by_test.items():
        stories, kind = _stories_by_test.get(nodeid, ((), "-"))
        if not stories:
            untagged += 1
        for story in stories:
            run[story][kind] += 1
            if outcome == "passed":
                passed[story][kind] += 1

    terminalreporter.section("User stories")
    if not run:
        terminalreporter.write_line("No test that ran names a user story.")
    for story in sorted(run):
        counts = ", ".join(
            f"{passed[story][kind]}/{run[story][kind]} ({kind})" for kind in _KIND_ORDER if run[story][kind]
        )
        terminalreporter.write_line(f"{story}: {counts}")
    terminalreporter.write_line(f"Tests that ran without naming a story: {untagged}")
