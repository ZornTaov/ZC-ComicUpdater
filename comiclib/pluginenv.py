#a plugin's program, run with what it needs: the python packages its plugin.json asks for, installed into a
#virtual environment of the plugin's own, in its folder. that folder is in the config folder, which is kept
#when the image is replaced, so a new image costs nothing - unless it brings a newer python, which a venv
#cannot outlive. the venv says what it was built for and from, and is built again whenever that changes,
#so the first run after such an update rebuilds it and says so in its log, rather than failing every night.
#
#and the programs it needs that pip cannot give - ffmpeg and the like - which it names, and which are only
#looked for: the container runs as the library's owner, and anything apt put in would go with the image.
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

VENV = ".venv"
#written last, so a build that was killed part way leaves none, and the next run builds it again
STAMP = "built.json"
#held while one is built, since two comics of one plugin can be due at once
LOCK = ".venv.lock"
#a lock older than this was left by a build that died, and is taken over
STALE = 60 * 60
#pip fetching a few packages; a build that takes longer than this is stuck
PIP_TIMEOUT = 30 * 60


class EnvError(Exception):
    #a plugin's program cannot be given what it needs, saying what to do about it
    pass


def install_block(manifest):
    block = manifest.get("install") or {}
    return block if isinstance(block, dict) else {}


def wants_env(manifest):
    #a plugin that asks for nothing runs with the updater's own python, as every plugin did before this
    block = install_block(manifest)
    return bool(block.get("pip") or block.get("requirements"))


def requirements_path(folder, manifest):
    #inside the plugin's folder and nowhere else, so a plugin.json cannot point pip at the config folder
    named = install_block(manifest).get("requirements")
    if not named:
        return None
    full = os.path.normpath(os.path.join(folder, named))
    if os.path.commonpath([os.path.abspath(folder), os.path.abspath(full)]) != os.path.abspath(folder):
        raise EnvError("its requirements file {0} is outside its own folder".format(named))
    return full


def env_python(folder):
    venv = os.path.join(folder, VENV)
    return os.path.join(venv, "Scripts", "python.exe") if os.name == 'nt' else os.path.join(venv, "bin", "python")


def recipe(folder, manifest):
    #what a venv is built from and for: the python it sits on, which a new image can change, and what it was
    #asked to install, which a plugin's update can. a venv whose stamp says anything else is built again
    path = requirements_path(folder, manifest)
    digest = hashlib.sha256()
    digest.update(json.dumps(install_block(manifest).get("pip") or [], sort_keys=True).encode())
    if path:
        try:
            with open(path, "rb") as f:
                digest.update(f.read())
        except OSError as error:
            raise EnvError("its requirements file cannot be read: {0}".format(error))
    return {"python": "{0}.{1}".format(*sys.version_info[:2]),
            "base": os.path.realpath(getattr(sys, "_base_executable", None) or sys.executable),
            "asked": digest.hexdigest()}


def built_for(folder):
    try:
        with open(os.path.join(folder, VENV, STAMP), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def state(folder, manifest):
    #for the page: None for a plugin that needs no venv, "ready", or "to build" - the next run builds it
    if not wants_env(manifest):
        return None
    try:
        ready = built_for(folder) == recipe(folder, manifest) and os.path.isfile(env_python(folder))
    except EnvError:
        return "to build"
    return "ready" if ready else "to build"


def missing_programs(manifest):
    #the programs it names in "needs" that are not on the path
    return [str(name) for name in manifest.get("needs") or [] if not shutil.which(str(name))]


class held:
    #one build at a time for a plugin, across processes: the lock is a file made only if it is not there
    def __init__(self, folder, say):
        self.path = os.path.join(folder, LOCK)
        self.say = say

    def __enter__(self):
        said = False
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > STALE:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                if not said:
                    self.say("Another run is installing this plugin's packages; waiting for it ...")
                    said = True
                time.sleep(2)

    def __exit__(self, *ignored):
        try:
            os.remove(self.path)
        except OSError:
            pass


def build(folder, manifest, say=print):
    #the venv made afresh and its packages installed, everything pip says passed on so the run's log has it.
    #made where it will stay rather than aside and moved: a venv's own scripts name the folder it was made in
    wanted = recipe(folder, manifest)
    venv = os.path.join(folder, VENV)
    shutil.rmtree(venv, ignore_errors=True)
    say("Building {0} for python {1} ...".format(venv, wanted["python"]))
    #the image's own packages, selenium among them, are seen from inside it, so a plugin asks only for what
    #it needs beyond them - and pip comes from there too, which spares making a copy of it in every venv
    steps = [[sys.executable, "-m", "venv", "--system-site-packages", "--without-pip", venv]]
    pip = [env_python(folder), "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    path = requirements_path(folder, manifest)
    if path:
        steps.append(pip + ["-r", path])
    asked = [str(name) for name in install_block(manifest).get("pip") or []]
    if asked:
        steps.append(pip + ["--"] + asked)
    for command in steps:
        say("  " + subprocess.list2cmdline(command))
        try:
            done = subprocess.run(command, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors="replace", timeout=PIP_TIMEOUT,
                                  env=dict(os.environ, PIP_NO_INPUT="1", PYTHONUNBUFFERED="1"))
        except (OSError, subprocess.SubprocessError) as error:
            raise EnvError("{0} could not be run: {1}".format(command[2] if len(command) > 2 else command[0], error))
        for line in (done.stdout or "").splitlines():
            say("    " + line)
        if done.returncode != 0:
            raise EnvError("installing its packages failed (exit {0}); what pip said is above. Fix its "
                           "plugin.json's \"install\", or its requirements file, and it is tried again on the "
                           "next run".format(done.returncode))
    with open(os.path.join(venv, STAMP), "w", encoding="utf-8") as f:
        json.dump(wanted, f, indent=1)
    say("Its packages are installed.")


def ensure(folder, manifest, say=print):
    #the python its program is run with: the updater's own for a plugin that asks for nothing, and otherwise
    #its venv's, built first if there is none or it was built for something else
    if not wants_env(manifest):
        return sys.executable
    if built_for(folder) == recipe(folder, manifest) and os.path.isfile(env_python(folder)):
        return env_python(folder)
    with held(folder, say):
        #another run may have built it while this one waited
        if not (built_for(folder) == recipe(folder, manifest) and os.path.isfile(env_python(folder))):
            was = built_for(folder)
            if was and was.get("python") != recipe(folder, manifest)["python"]:
                say("Its packages were installed for python {0}, and this is {1}, so they are installed "
                    "again.".format(was.get("python"), recipe(folder, manifest)["python"]))
            build(folder, manifest, say)
    return env_python(folder)
