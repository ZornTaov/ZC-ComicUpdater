#the status column's expression, lifted out of the page and run in node against made-up comics, so the
#page's own logic is what is checked rather than a copy of it.
import os
import shutil
import subprocess

import pytest

from conftest import PROJECT

ROWS = """[
  {what: "primed", exit_code: 0, completed: false, stop_reason: "primed"},
  {what: "finished", exit_code: 0, completed: true, stop_reason: "no next button"},
  {what: "older run with no flag", exit_code: 0, completed: undefined, stop_reason: "no next button"},
  {what: "stopped part way", exit_code: 0, completed: false, stop_reason: "page load timed out"},
  {what: "failed", exit_code: 3, completed: false, stop_reason: "next link runs backwards"},
  {what: "never run", exit_code: null, completed: undefined, stop_reason: null},
  {what: "ended", exit_code: 0, completed: true, ended: true, stop_reason: "no next button"}
]"""


@pytest.fixture(scope="module")
def status():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH, so the page's own expression cannot be run")
    with open(os.path.join(PROJECT, "web_page", "js", "library.js"), encoding="utf-8") as f:
        html = f.read()
    block = html[html.index("const waiting = c.exit_code === 0"):html.index("const bad = c.problem")]
    script = ("const rows = {0};\nfor (const c of rows) {{\n{1}\n"
              "  console.log(c.what + '|' + result + '|' + (waiting ? 'waiting' : '-'));\n}}\n").format(ROWS, block)
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, "node could not run it: " + done.stderr[:400]
    return dict(line.split("|", 1) for line in done.stdout.strip().splitlines())


def test_a_primed_comic_does_not_claim_to_be_up_to_date(status):
    assert "up to date" not in status["primed"] and "primed" in status["primed"], status["primed"]
    assert status["primed"].endswith("waiting"), status["primed"]


def test_a_comic_followed_to_its_end_is_up_to_date(status):
    assert status["finished"] == "up to date|-", status["finished"]


def test_an_older_run_with_no_flag_still_reads_as_up_to_date(status):
    assert status["older run with no flag"] == "up to date|-", status["older run with no flag"]


def test_a_run_that_stopped_part_way_says_so(status):
    assert "stopped early" in status["stopped part way"], status["stopped part way"]


def test_a_failure_still_shows_its_exit_code(status):
    assert status["failed"].startswith("exit 3"), status["failed"]


def test_a_comic_never_run_shows_nothing_odd(status):
    assert "up to date" not in status["never run"], status["never run"]


def test_an_ended_comic_reads_as_ended(status):
    assert status["ended"].startswith("ended"), status["ended"]
