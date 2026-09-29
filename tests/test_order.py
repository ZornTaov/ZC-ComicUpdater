#update_comics running comics side by side must report each as it finishes, not in the order they started:
#a slow comic started first once held up the whole log behind it.
import pytest

from conftest import run, write_meta

pytestmark = pytest.mark.slow

#a stand-in for mirror_base that sleeps for however long its url says, so the slow comic can be made the
#one started first
FAKE_MIRROR = ("import sys, time\n"
               "url = sys.argv[-1]\n"
               "time.sleep(float(url.rsplit('/', 1)[-1]))\n"
               "print('slept for', url.rsplit('/', 1)[-1])\n")


def test_quick_comics_are_reported_before_a_slow_one_started_first(tmp_path, library):
    fake = tmp_path / "fake_mirror.py"
    fake.write_text(FAKE_MIRROR)
    #the slow one sorts first by name, so it is submitted first
    plan = [("A_Slow", 6), ("B_Quick", 1), ("C_Quick", 1), ("D_Quick", 1)]
    for name, delay in plan:
        write_meta(library / "Uncompressed" / name, {
            "schema": 2,
            "settings": {"url": "https://example.com/{0}".format(delay), "output": "Uncompressed/" + name,
                         "cbz_path": None, "increment": 1, "prefix": False, "javascript": False,
                         "firefox": False, "waittime": 0, "cbz": True, "ended": False},
            "state": {"page_count": 0}, "history": {"runs": []}})
    done = run("update_comics.py", library, "--jobs", "2", "--script", fake)
    lines = [line for line in done.stdout.splitlines() if line.startswith("[")]
    order = [line.split()[1] for line in lines]
    assert len(order) == len(plan), done.stdout[-600:]
    slow_at = next(i for i, name in enumerate(order) if "A_Slow" in name)
    assert slow_at > 0, "the slow comic still blocks the log:\n" + "\n".join(lines)
