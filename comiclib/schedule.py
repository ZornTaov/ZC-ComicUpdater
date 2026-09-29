#when an update runs: once a day at a set time, or straight away when an update-now file turns up in the
#library.
import os
import time
from datetime import datetime, timedelta

#dropping a file of this name into the library root starts an update without waiting for the schedule,
#which is the whole interface a container needs: anything that can reach the share can make the file.
#either spelling counts, since windows hides the extension on a new text document
trigger_files = ("update-now", "update-now.txt")
#how often a scheduled wait looks for one
trigger_poll = 30
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


def wait_until(target, root):
    #sleeps towards the scheduled time in short steps, returning early with the comics a trigger file names
    while True:
        left = (target - datetime.now()).total_seconds()
        if left <= 0:
            return None
        time.sleep(min(left, trigger_poll))
        wanted = take_trigger(root)
        if wanted is not None:
            return wanted
