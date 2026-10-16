#one run of a plugin comic: its plugin's program, pointed at the comic and left to write in the comic's
#staging folder; what it wrote taken in as pages and chapters; where it got to remembered for next time;
#the run written into the comic's metadata the way a scrape writes its own; and the archive kept up.
import os
import shutil
import signal
import subprocess
import time
import traceback

from comiclib import exits, intake, plugins, pluginsetup
from comiclib.batch import kill_tree, own_group
from comiclib.cbz import update as update_archive
from comiclib.metadata import METADATA_FILE, now_stamp, read as read_metadata, write as write_metadata
from comiclib.runrecord import max_runs

#how long a program told to stop is given to stop before it is made to
GRACE = 15


def leading_own_group():
    #the batch starts this in a process group of its own and, on a timeout or a stop, kills the whole group.
    #the program then has to stay in it, or it would be left running with nothing to stop it. run by hand
    #from a shell, this is in the shell's group, and the program gets one of its own
    return os.name != 'nt' and os.getpgrp() == os.getpid()


def stop_program(process):
    #the program and whatever it started - a browser, as often as not - stopped, this process carrying on
    if not leading_own_group():
        kill_tree(process)
        return
    #sharing a group with the program, so the group is told to stop with this process deaf to it for as
    #long as that takes, and the program made to if it has not
    was = signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        os.killpg(os.getpgrp(), signal.SIGTERM)
        try:
            process.wait(timeout=GRACE)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=GRACE)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        signal.signal(signal.SIGTERM, was)


def run_program(command, staging, deadline, setup=None):
    #(exit code, stopped for time). its output goes straight to this one's, so the batch's last line and
    #the web page's Running now follow it as it goes. setup is the plugin's own settings, handed over in its
    #environment, where neither the log nor the run record ever sees them
    try:
        process = subprocess.Popen(command, cwd=staging, env=dict(os.environ, PYTHONUNBUFFERED="1", **(setup or {})),
                                   **({} if leading_own_group() else own_group()))
    except OSError as error:
        print("ERROR: could not start {0}: {1}. Check the plugin's command, and that its program is where "
              "it says.".format(command[0], error))
        return None, False
    try:
        process.wait(timeout=deadline or None)
        return process.returncode, False
    except subprocess.TimeoutExpired:
        print("The plugin's program has run for {0:.0f}s, so it is being stopped and what it fetched taken "
              "in; the next run carries on from there.".format(deadline), flush=True)
        stop_program(process)
        return process.returncode, True


def ended_change(metadata, said):
    #what the plugin's answer to ended() does to a comic: "mark" it ended, "rearm" it to be marked again,
    #or nothing. ended is the reader's judgement, which a plugin can only offer. history.plugin_ended says
    #the plugin has said complete and has not since said otherwise: while it stands, a comic the person
    #unticked stays unticked, however often the plugin says the same thing. once the plugin says it is not
    #complete - a series that came back - that is forgotten, and when it says complete again, the comic is
    #marked again. no answer (None) changes nothing, so a check that failed neither marks nor rearms
    if (metadata.get("settings") or {}).get("ended"):
        return None
    marked = "plugin_ended" in (metadata.get("history") or {})
    if said is True and not marked:
        return "mark"
    if said is False and marked:
        return "rearm"
    return None


def page_count(folder):
    return len([name for name in os.listdir(folder)
                if name != METADATA_FILE and os.path.isfile(os.path.join(folder, name))])


def record_run(folder, metadata, plugin, state, run, ended=None):
    #the metadata as it is on disk now, so a change made while the program ran is kept, with what this run
    #learned laid over it: where the program got to, the chapters it added, and the run itself. ended is the
    #plugin's answer to whether the comic is complete, True, False or None (see ended_change)
    fresh = read_metadata(folder) or metadata
    fresh["generator"] = "plugin:" + plugin.name
    fresh["generator_version"] = plugin.version
    fresh["updated"] = now_stamp()
    kept = fresh.setdefault("state", {})
    kept.update(page_count=page_count(folder), completed=run["completed"], plugin=state)
    if metadata.get("chapters") is not None:
        fresh["chapters"] = metadata["chapters"]
    history = fresh.setdefault("history", {})
    #asked of the file as it is now, so an untick made while the program ran is the one that counts
    change = ended_change(fresh, ended)
    if change == "mark":
        fresh.setdefault("settings", {})["ended"] = True
        history["plugin_ended"] = now_stamp()
        run["marked_ended"] = True
        print("The plugin says this comic is complete, so it is marked ended and left alone from now on. Untick "
              "\"ended\" in its settings to keep checking; it is marked again only once the plugin has said it "
              "is not complete and then that it is.", flush=True)
    elif change == "rearm":
        del history["plugin_ended"]
        run["ended_rearmed"] = True
        print("The plugin no longer says this comic is complete, so it will be marked ended again when it does.",
              flush=True)
    runs = list(history.get("runs") or [])
    #the same failure day after day is one fault that has gone on a while, as a scrape counts it, so twenty
    #copies of it do not push every run that worked out of the record
    last = runs[-1] if runs else {}
    if (run["pages_saved"] == 0 and run["exit_code"] not in (None, exits.OK)
            and last.get("pages_saved") == 0 and last.get("exit_code") == run["exit_code"]):
        run["since"] = last.get("since") or last.get("started")
        run["times"] = (last.get("times") or 1) + 1
        runs = runs[:-1]
    runs.append(run)
    if len(runs) > max_runs:
        runs = runs[:1] + runs[-(max_runs - 1):]
    history["runs"] = runs
    write_metadata(folder, fresh)
    return fresh


def run(folder, deadline=0):
    #the exit code says how it went, as a scrape's does
    try:
        return run_comic(folder, deadline)
    except Exception:  # noqa: BLE001 - anything else is a fault here, said in full so it can be found
        traceback.print_exc()
        return exits.UNEXPECTED


def run_comic(folder, deadline):
    metadata = read_metadata(folder)
    if not metadata:
        print("ERROR: {0} has no {1} that can be read. Start a plugin comic with run_plugin.py --add.".format(
            folder, METADATA_FILE))
        return exits.USAGE
    settings = metadata.get("settings") or {}
    if not settings.get("scraper"):
        print("ERROR: {0} is not scraped by a plugin; run it with mirror_base.py, or update_comics.py.".format(
            folder))
        return exits.USAGE
    try:
        plugin = plugins.load(settings["scraper"])
    except plugins.PluginError as error:
        print("ERROR: {0}".format(error))
        return exits.USAGE
    #its packages, installed now if this is its first run or a new image has come since the last. a failure
    #is the program's not being able to run, so it is counted as the program failing, day after day, until
    #it is fixed - and what a run killed part way left behind is still there for the run that can
    try:
        plugin.ready(lambda line: print(line, flush=True))
    except plugins.PluginError as error:
        print("ERROR: {0}".format(error), flush=True)
        return exits.TOOL_FAILED

    #the plugin's own settings, for its plugin.py as settings["setup"]: read now, as a run's other settings
    #are, and never written into the comic's metadata, which settings itself is not
    settings = dict(settings, setup=pluginsetup.values(plugin))
    started = now_stamp()
    state = dict((metadata.get("state") or {}).get("plugin") or {})
    was_state = dict(state)
    pages, chapters = [], []
    last = None
    #in full, since the program is run inside it: told a relative path, a program resolves it against
    #staging itself and writes into a copy of the comic's path nested within
    staging = os.path.abspath(intake.staging_folder(folder))

    def take(cut_short):
        nonlocal state, last
        taken = last = intake.take_in(plugin, folder, metadata, cut_short)
        intake.record_chapters(folder, metadata, taken.chapters)
        if taken.comicinfo and not metadata.get("comicinfo"):
            #what the program said of the whole comic, the first time it says anything
            metadata["comicinfo"] = taken.comicinfo
        state = intake.remember(plugin, state, taken) or state
        pages.extend(taken.pages)
        chapters.extend(chapter["label"] for chapter in taken.chapters)

    #a run before this one that was killed - by the batch's timeout, or stopped from the page - left what
    #its program had fetched. whatever of it is whole is taken in before the program is asked for more
    if os.path.isdir(staging) and intake.files_under(staging):
        print("Taking in what a run that was stopped part way left behind ...", flush=True)
        take(cut_short=True)
    else:
        #an empty one left by a run killed before its program wrote anything
        shutil.rmtree(staging, ignore_errors=True)

    try:
        command = plugins.build_command(plugin, settings, state, staging)
    except plugins.PluginError as error:
        print("ERROR: {0}".format(error))
        return exits.USAGE
    os.makedirs(staging, exist_ok=True)
    print("Running {0}: {1}".format(plugin.title, subprocess.list2cmdline(command)), flush=True)
    began = time.time()
    said, out_of_time = run_program(command, staging, deadline, pluginsetup.environment(plugin))
    take(cut_short=out_of_time)
    #asked only of a run whose program finished, since one that failed or ran out of time cannot know it has
    #it all, and only of a comic not ended already - which every run of one unticked by hand is
    ended = (intake.ended(plugin, settings, state, last)
             if said == 0 and not out_of_time and not settings.get("ended") else None)

    if out_of_time:
        code, why = exits.TOOL_OUT_OF_TIME, "stopped after {0:.0f}s".format(time.time() - began)
    elif said == 0:
        code, why = exits.OK, "the plugin's program finished"
    else:
        code = exits.TOOL_FAILED
        why = ("the plugin's program could not be started" if said is None
               else "the plugin's program ended with exit code {0}".format(said))
    print("Took in {0} page(s){1}. {2}.".format(
        len(pages), " in {0} chapter(s)".format(len(chapters)) if chapters else "", why[0].upper() + why[1:]),
        flush=True)

    #a run that took nothing in and ended as well as the one before it has nothing to add to the record,
    #and rewriting the file every day would carry it into the archive every day for nothing
    runs = (metadata.get("history") or {}).get("runs") or []
    was_well = runs and runs[-1].get("exit_code") in (None, exits.OK)
    if not pages and code == exits.OK and was_well and state == was_state and not ended_change(metadata, ended):
        return code
    record_run(folder, metadata, plugin, state, {
        "run_id": started,
        "started": started,
        "updated": now_stamp(),
        "argv": command,
        "pages_saved": len(pages),
        "chapters_taken": chapters,
        "completed": code == exits.OK,
        "stop_reason": why,
        "exit_code": code,
    }, ended)

    #a comic in chapters is packed one archive per chapter by the batch once this is done; one that is not
    #keeps a single archive, kept up here the way a scrape keeps its own
    fresh = read_metadata(folder)
    if (pages and (fresh.get("settings") or {}).get("cbz") is not False
            and not (fresh.get("chapters") or {}).get("list") and not (fresh.get("chapters") or {}).get("every")):
        archive, added = update_archive(folder, (fresh.get("settings") or {}).get("cbz_path"))
        if archive:
            print("Archive {0}: {1} page(s) added.".format(archive, added))
    return code
