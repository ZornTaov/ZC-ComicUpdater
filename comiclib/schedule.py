#when an update runs: once a day at a set time, or straight away when an update-now file turns up in the
#library. and when the long-running process stops altogether, for a restart file.
import os
import sys
import time
from datetime import datetime, timedelta

#dropping a file of this name into the library root starts an update without waiting for the schedule,
#which is the whole interface a container needs: anything that can reach the share can make the file.
#either spelling counts, since windows hides the extension on a new text document
trigger_files = ("update-now", "update-now.txt")
#and dropping one of this name there makes the process finish what it is doing and exit, which a container
#set to restart unless stopped answers by starting it again - reading every script afresh. it is the only
#way to restart the container for someone who can reach the share but not the machine running it
restart_files = ("restart", "restart.txt")
#what a wait returns when it found a restart file rather than a time or an update-now file
RESTART = "restart"
#how often a scheduled wait looks for one
trigger_poll = 30
#how often a restart looks again at whether the jobs it is waiting for have finished
restart_poll = 5
#trigger files that could not be read, so each is complained about once rather than every poll
ignored_triggers = set()


def parse_schedule(text):
    hour, _, minute = text.partition(':')
    hour, minute = int(hour), int(minute)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(text)
    return hour, minute


def next_run(hour, minute):
    #worked out fresh before every sleep, so the daily time stays put across a clock change
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def local_zone():
    #what the machine believes its timezone is. in a container that is UTC unless TZ was passed in, which
    #is worth saying out loud: the schedule would otherwise quietly run hours away from when it was meant to
    return datetime.now().astimezone().tzname() or time.tzname[0]


def take_trigger(root):
    #returns the comics a trigger file asks for (an empty list meaning all of them), or None when there is
    #no trigger. the file is removed first, so a run that fails is not started again every half minute
    for name in trigger_files:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                wanted = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
            os.remove(path)
        except (OSError, UnicodeDecodeError) as error:
            #left in place it would fire on every poll, so it is reported once and then ignored until replaced
            key = (path, os.path.getmtime(path) if os.path.exists(path) else None)
            if key in ignored_triggers:
                continue
            ignored_triggers.add(key)
            print("WARNING: could not read and remove {0}, so it is being ignored: {1}".format(path, error),
                  flush=True)
            continue
        return [w.replace('\\', '/').strip('/') for w in wanted]
    return None


def restart_file(root):
    #the restart file waiting in the library, if there is one that has not already been given up on
    for name in restart_files:
        path = os.path.join(root, name)
        try:
            if os.path.isfile(path) and (path, os.path.getmtime(path)) not in ignored_triggers:
                return path
        except OSError:
            #removed between the two looks, which is the same as not there
            continue
    return None


def wait_until(target, root):
    #sleeps towards the scheduled time in short steps, returning early with the comics a trigger file names,
    #or RESTART for a restart file. that is looked for first, so an update-now dropped beside it is left
    #where it is for the process that starts next. looked for before the first sleep as well, so one dropped
    #while the process was down is acted on as it starts rather than half a minute later
    if restart_file(root):
        return RESTART
    while True:
        left = (target - datetime.now()).total_seconds()
        if left <= 0:
            return None
        time.sleep(min(left, trigger_poll))
        if restart_file(root):
            return RESTART
        wanted = take_trigger(root)
        if wanted is not None:
            return wanted


def ready_to_restart(root, runner=None):
    #True once the process can exit for a restart: every job finished and the file gone. waits for the jobs
    #rather than stopping them, since a restart is asked for between things and a scrape killed part way
    #has to be carried on later. False when the file went away while waiting - taken back - or could not
    #be removed: left in place, it would restart the container again every time it started, for good
    path = restart_file(root)
    if path is None:
        return False
    if runner is not None:
        said = False
        #closing the queue in the same step that finds it empty, so nothing the page adds in between starts
        #only to be cut off by the exit
        while not runner.close_if_idle():
            if not said:
                current = runner.current
                busy = current.label if current else "{0} job(s) waiting".format(len(runner.waiting))
                print("Found {0}; restarting once the queue is empty. Running now: {1}".format(
                    os.path.basename(path), busy), flush=True)
                said = True
            time.sleep(restart_poll)
            if restart_file(root) is None:
                runner.reopen()
                print("The restart file was taken away, so not restarting.", flush=True)
                return False
    try:
        os.remove(path)
    except OSError as error:
        if runner is not None:
            runner.reopen()
        ignored_triggers.add((path, os.path.getmtime(path) if os.path.exists(path) else None))
        print("WARNING: could not remove {0}, so not restarting - it would only restart again every time it "
              "started: {1}".format(path, error), flush=True)
        return False
    if runner is not None:
        #written before the exit, so the updater that starts next shows it under Recent
        runner.note("restart", "Restarted, as {0} asked".format(os.path.basename(path)))
    print("Restarting: exiting so the container starts this again, reading the scripts afresh.", flush=True)
    sys.stdout.flush()
    return True
