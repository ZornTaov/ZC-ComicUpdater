#a restart file in the library makes the long-running process wait for whatever is running, remove the file
#and exit, for a container set to restart unless stopped to start it again. the file goes before the exit,
#or the container would restart every time it started; one that cannot be removed is no restart at all.
#and the page's Recent list, kept in the config folder for a week, shows the restart once it is back.
import json
import threading
import time
from datetime import datetime, timedelta

import pytest

from comiclib.web.jobs import Job
from conftest import free_port, fresh, run


@pytest.fixture
def schedule(config):
    module = fresh("comiclib.schedule")
    module.trigger_poll = 0.2
    module.restart_poll = 0.1
    return module


@pytest.fixture
def runner(config):
    return fresh("comiclib.web.jobs").Runner(None, None)


def held_job(runner):
    #a job that runs until let go, standing in for a scrape
    started, release = threading.Event(), threading.Event()

    def work(job):
        started.set()
        release.wait(30)
        return 0

    job = runner.submit(Job("update", "Held", work))
    assert started.wait(10), "the job never started"
    return job, release


def in_background(call):
    result = []
    thread = threading.Thread(target=lambda: result.append(call()), daemon=True)
    thread.start()
    return thread, result


def an_hour_away():
    return datetime.now() + timedelta(hours=1)


def test_a_restart_file_ends_the_wait_and_leaves_an_update_now_for_later(schedule, library):
    (library / "restart.txt").write_text("", encoding="utf-8")
    (library / "update-now.txt").write_text("MyComic", encoding="utf-8")
    assert schedule.wait_until(an_hour_away(), str(library)) is schedule.RESTART
    assert (library / "update-now.txt").exists(), "the update is for the process that starts next"


def test_a_restart_file_turning_up_while_waiting_ends_the_wait(schedule, library):
    started = time.time()
    threading.Timer(0.5, lambda: (library / "restart").write_text("")).start()
    assert schedule.wait_until(an_hour_away(), str(library)) is schedule.RESTART
    assert time.time() - started < 5


def test_a_restart_waits_for_the_running_job_and_removes_the_file(schedule, runner, library):
    job, release = held_job(runner)
    (library / "restart.txt").write_text("", encoding="utf-8")
    thread, result = in_background(lambda: schedule.ready_to_restart(str(library), runner))
    time.sleep(0.5)
    assert not result, "it should not restart while a job is running"
    assert (library / "restart.txt").exists(), "nor remove the file before it is ready to"
    release.set()
    thread.join(10)
    assert result == [True], result
    assert not (library / "restart.txt").exists(), "removed before the exit, or it would restart for ever"
    assert job.finished, "the job was let finish, not stopped"
    #and nothing queued from now on starts, to be cut off by the exit
    late = threading.Event()
    runner.submit(Job("update", "Late", lambda job: late.set()))
    assert not late.wait(0.5), "a job queued after the queue closed should not start"


def test_taking_the_file_away_while_waiting_calls_the_restart_off(schedule, runner, library):
    _, release = held_job(runner)
    (library / "restart.txt").write_text("", encoding="utf-8")
    thread, result = in_background(lambda: schedule.ready_to_restart(str(library), runner))
    time.sleep(0.3)
    (library / "restart.txt").unlink()
    thread.join(10)
    assert result == [False], result
    release.set()
    after = threading.Event()
    runner.submit(Job("update", "After", lambda job: after.set()))
    assert after.wait(10), "the queue should run jobs again once the restart is called off"


def test_a_restart_file_that_cannot_be_removed_is_no_restart(schedule, library, monkeypatch, capsys):
    (library / "restart.txt").write_text("", encoding="utf-8")

    def refuse(path):
        raise PermissionError("read-only share")

    monkeypatch.setattr(schedule.os, "remove", refuse)
    assert schedule.ready_to_restart(str(library)) is False
    assert "could not remove" in capsys.readouterr().out
    #and it is not acted on again every half minute, only once replaced
    assert schedule.restart_file(str(library)) is None


@pytest.mark.parametrize("how", [["--web", "PORT", "--web-host", "127.0.0.1"], ["--schedule", "03:30"]],
                         ids=["web", "schedule"])
def test_the_updater_exits_cleanly_on_a_restart_file(library, config, how):
    (library / "restart.txt").write_text("", encoding="utf-8")
    how = [str(free_port()) if part == "PORT" else part for part in how]
    done = run("update_comics.py", library, "--progress", "0", "--config", config, *how, timeout=60)
    assert done.returncode == 0, done.stdout[-600:]
    assert "Restarting" in done.stdout, done.stdout[-600:]
    assert not (library / "restart.txt").exists()


def wait_for(job):
    end = time.time() + 10
    while job.finished is None and time.time() < end:
        time.sleep(0.05)
    assert job.finished, "the job never finished"


def test_recent_outlasts_a_restart_and_numbers_jobs_on_from_it(config):
    jobs = fresh("comiclib.web.jobs")
    before = jobs.Runner(None, None)
    first = before.submit(Job("update", "Before the restart", lambda job: 0))
    wait_for(first)
    #written a moment after the job finishes, and after the page is shown it
    end = time.time() + 10
    while not (config / "recent.json").exists() and time.time() < end:
        time.sleep(0.05)
    #a fresh process, as the container starting again is
    after = fresh("comiclib.web.jobs").Runner(None, None)
    assert [entry["label"] for entry in after.recent] == ["Before the restart"], after.recent
    second = after.submit(Job("update", "After the restart", lambda job: 0))
    assert second.id > first.id, "a job since the restart must not share a number with one before it"


def test_recent_forgets_what_finished_more_than_a_week_ago(config):
    jobs = fresh("comiclib.web.jobs")
    now = time.time()
    held = [{"id": 2, "label": "Yesterday", "finished": now - 86400},
            {"id": 1, "label": "Last month", "finished": now - 30 * 86400}]
    (config / "recent.json").write_text(json.dumps(held), encoding="utf-8")
    assert [entry["label"] for entry in jobs.Runner(None, None).recent] == ["Yesterday"]


def test_a_damaged_recent_file_starts_recent_empty(config, capsys):
    (config / "recent.json").write_text("{not json", encoding="utf-8")
    assert fresh("comiclib.web.jobs").Runner(None, None).recent == []
    assert "could not read" in capsys.readouterr().out


def test_a_restart_shows_under_recent_once_the_updater_is_back(library, config, web):
    (library / "restart.txt").write_text("", encoding="utf-8")
    done = run("update_comics.py", library, "--progress", "0", "--config", config,
               "--web", free_port(), "--web-host", "127.0.0.1", timeout=60)
    assert done.returncode == 0, done.stdout[-600:]
    #the updater that starts next, as the container brings it back
    _, state = web().call("/api/state")
    assert [(entry["kind"], entry["label"]) for entry in state["history"]][:1] == \
        [("restart", "Restarted, as restart.txt asked")], state["history"][:2]
