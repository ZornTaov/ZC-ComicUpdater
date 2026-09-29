#a site whose page never finishes loading. without a limit of its own the browser waits out selenium's own
#two minute http timeout, and a comic that hangs holds up every comic queued behind it. the run should give
#up quickly, with its own exit code, and a batch should name the stall for what it is rather than call it
#interrupted.
import time

import pytest

from conftest import Comic, run, write_meta

pytestmark = [pytest.mark.browser, pytest.mark.slow]


def test_a_page_that_never_loads_fails_fast_with_its_own_exit_code(tmp_path, stalling):
    started = time.time()
    done = run("mirror_base.py", "-o", tmp_path / "comic", "--no-cbz", stalling + "/page",
               cwd=tmp_path, env={"MIRROR_PAGE_TIMEOUT": "8"}, timeout=240)
    elapsed = time.time() - started
    said = done.stdout + done.stderr
    assert done.returncode == 6, "{0}: {1}".format(done.returncode, said.strip()[-300:])
    #the old behaviour waited 120s for selenium's own http timeout
    assert elapsed < 60, "took {0:.0f}s".format(elapsed)
    assert "Traceback" not in said, said.strip()[-500:]


def test_a_batch_names_a_stall_rather_than_calling_it_interrupted(library, stalling, serve):
    #one comic that stalls, and one that is fine, run side by side the way the container runs them
    comics = {"Stalls": stalling + "/never", "Fine": serve(Comic) + "/p/1"}
    for name, url in comics.items():
        write_meta(library / "Uncompressed" / name, {
            "schema": 2,
            "settings": {"url": url, "output": "Uncompressed/" + name, "cbz_path": None,
                         "increment": 1, "prefix": False, "javascript": False, "firefox": False,
                         "waittime": 0, "cbz": False, "ended": False},
            "state": {"page_count": 0}, "history": {"runs": []},
        })
    started = time.time()
    done = run("update_comics.py", library, "--jobs", "2", env={"MIRROR_PAGE_TIMEOUT": "8"}, timeout=300)
    elapsed = time.time() - started
    assert "page load timed out" in done.stdout, done.stdout[-1500:]
    assert "Traceback" not in done.stdout, done.stdout[-1500:]
    assert "interrupted" not in done.stdout, done.stdout[-1500:]
    assert elapsed < 90, "took {0:.0f}s".format(elapsed)
