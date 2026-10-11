#the pool of chrome profiles the suite's browsers share: each claimed by one process at a time, however many
#ask at once, free again the moment its claimer ends however it ends, and never handed out while a chrome
#is still closing on it. two chromes on one profile is a scrape that will not start, and it failed tests
#by chance - a claim read in the moment between its making and its process id being written was taken for
#one left by the dead, and the profile handed out twice.
import os
import subprocess
import sys

from comiclib.browser import claim_profile

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#a process that claims a profile, says which, and holds it until told to let go
CLAIMER = """
import sys
from comiclib.browser import claim_profile
profile, held = claim_profile(sys.argv[1])
print(profile, flush=True)
sys.stdin.read()
"""


def claimer(tmp_path, pool):
    script = tmp_path / "claimer.py"
    script.write_text(CLAIMER, encoding="utf-8")
    return subprocess.Popen([sys.executable, str(script), str(pool)], cwd=PROJECT, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env=dict(os.environ, PYTHONPATH=PROJECT))


def test_many_claiming_at_once_each_get_a_profile_of_their_own(tmp_path):
    #a race, so tried several times over: one round of twelve caught the old claim's double handing-out four
    #times in ten, and five rounds nineteen in twenty. what makes it impossible rather than unlikely - a held
    #lock refusing every other handle - is pinned down without any timing by the test after next
    for round in range(5):
        pool = tmp_path / "pool{0}".format(round)
        started = [claimer(tmp_path, pool) for _ in range(12)]
        try:
            claimed = [process.stdout.readline().strip() for process in started]
        finally:
            for process in started:
                process.communicate("", timeout=30)
        assert "None" not in claimed, claimed
        assert len(set(claimed)) == len(claimed), sorted(claimed)


def test_a_profile_is_free_again_once_its_claimer_is_killed(tmp_path):
    pool = tmp_path / "pool"
    holder = claimer(tmp_path, pool)
    first = holder.stdout.readline().strip()
    profile, held = claim_profile(str(pool))
    assert profile != first, "a profile in use was handed out again"
    held.close()
    holder.kill()
    holder.wait(timeout=30)
    #no claim left behind to be judged dead or alive: the system let go of the lock when the process ended
    profile, held = claim_profile(str(pool))
    try:
        assert profile == first, (profile, first)
    finally:
        held.close()


def test_one_process_asking_twice_gets_two_profiles(tmp_path):
    pool = str(tmp_path / "pool")
    one, first = claim_profile(pool)
    two, second = claim_profile(pool)
    try:
        assert one != two
    finally:
        first.close()
        second.close()
    #and a profile let go of is the first handed out again
    again, held = claim_profile(pool)
    held.close()
    assert again == one


def test_a_profile_a_chrome_is_still_closing_on_is_passed_over(tmp_path):
    pool = tmp_path / "pool"
    profile = pool / "0"
    profile.mkdir(parents=True)
    if os.name == "nt":
        #chrome keeps this open while any of its processes lives, so it cannot be removed
        kept = open(str(profile / "lockfile"), "w")
    else:
        os.symlink("somehost-{0}".format(os.getpid()), str(profile / "SingletonLock"))
        kept = None
    try:
        chosen, held = claim_profile(str(pool))
        held.close()
        assert os.path.basename(chosen) == "1", chosen
    finally:
        if kept:
            kept.close()
    #once chrome has let go, the profile is used again, and the lock it left is cleared
    if os.name != "nt":
        os.remove(str(profile / "SingletonLock"))
    chosen, held = claim_profile(str(pool))
    held.close()
    assert os.path.basename(chosen) == "0", chosen
