#a plugin put in the config folder's plugins/ from its git repository, brought up to date from it, or taken
#out. cloned beside the others under a name no plugin can have, checked, and only then renamed to the id its
#plugin.json gives, so an install that fails leaves nothing behind that looks like a plugin. its packages
#are installed straight after, so they are ready before its first comic is due.
#
#installing from the web page runs code from anywhere on this machine, so it is allowed only behind a
#password, or where whoever set the container up has said, in its environment, that they mean it to be.
import json
import os
import re
import shutil
import subprocess
import sys
import uuid

from comiclib import pluginenv, plugins

#the opt-in for a page with no password. read from the environment, which nothing the page does can change
ALLOW = "MIRROR_ALLOW_PLUGIN_INSTALLS"
#a clone of a plugin with its tool can be large, and a slow host slower, but not this slow
GIT_TIMEOUT = 15 * 60
#where a clone is made before it is known to be a plugin: begins with '.', so installed() never lists it
CLONING = ".installing-"
#an address git is handed: never one beginning with '-', which it would take as an option
ADDRESS = re.compile(r'^(https?://|ssh://|git://|file://|[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:)\S+$')


class FetchError(Exception):
    pass


def truthy(text):
    return str(text or "").strip().lower() in ("1", "true", "yes", "on")


def page_may_install():
    #(allowed, why not): the web page's install, update and remove
    if os.environ.get("MIRROR_WEB_PASSWORD"):
        return True, None
    if truthy(os.environ.get(ALLOW)):
        return True, None
    return False, ("Installing plugins from the page runs whatever they hold on this machine, so it needs "
                   "a password: set MIRROR_WEB_PASSWORD, or set {0}=yes to allow it without one.".format(ALLOW))


def git(*arguments, cwd=None, say=print):
    #git run with what it says passed on. a folder copied in from another machine belongs to someone else,
    #and git refuses to work in one unless it is told the folder is safe - which, being a plugin of this
    #library, it is
    if shutil.which("git") is None:
        raise FetchError("this has no git. Pull a newer image, which has it, or put the plugin's folder in {0} "
                         "by hand".format(plugins.plugins_folder()))
    command = ["git", "-c", "safe.directory=*", "-c", "advice.detachedHead=false"] + list(arguments)
    say("  " + subprocess.list2cmdline(command))
    try:
        done = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              errors="replace", timeout=GIT_TIMEOUT,
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.SubprocessError) as error:
        raise FetchError("git could not be run: {0}".format(error))
    for line in (done.stdout or "").splitlines():
        say("    " + line)
    if done.returncode != 0:
        raise FetchError("git {0} failed (exit {1}); what it said is above".format(arguments[0], done.returncode))
    return done.stdout or ""


def read_manifest(folder):
    try:
        with open(os.path.join(folder, plugins.MANIFEST), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FetchError("it has no {0} at its top, so it is not a plugin".format(plugins.MANIFEST))
    except (OSError, ValueError) as error:
        raise FetchError("its {0} cannot be read: {1}".format(plugins.MANIFEST, error))


def keep_out(folder):
    #the venv and its lock are this machine's, not the plugin's, as is what python caches of its plugin.py as
    #it loads it: kept out of its git status by the clone's own exclude file, so the plugin's repository
    #needs to know nothing of them
    path = os.path.join(folder, ".git", "info", "exclude")
    if not os.path.isdir(os.path.join(folder, ".git")):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            held = f.read().splitlines()
    except OSError:
        held = []
    wanted = [line for line in ("/" + pluginenv.VENV + "/", "/" + pluginenv.LOCK, "__pycache__/")
              if line not in held]
    if wanted:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join(line + "\n" for line in wanted))


def ready_packages(name, say):
    #its packages installed now rather than by its first run. a failure leaves the plugin in place: its
    #first run tries again, and says why again if it still cannot
    plugin = plugins.load(name, with_hooks=False)
    keep_out(plugin.folder)
    try:
        plugin.ready(say)
    except plugins.PluginError as error:
        say("WARNING: {0}".format(error))
        return False
    return True


def install(address, ref=None, say=print):
    #the plugin's name once it is in place
    address = str(address or "").strip()
    if not ADDRESS.match(address):
        raise FetchError("{0!r} is not a git address: give the repository's https:// or git@ address".format(address))
    ref = str(ref or "").strip() or None
    if ref and (ref.startswith("-") or not re.match(r'^[\w./-]+$', ref)):
        raise FetchError("{0!r} is not a branch or tag".format(ref))
    home = plugins.plugins_folder()
    os.makedirs(home, exist_ok=True)
    aside = os.path.join(home, CLONING + uuid.uuid4().hex[:8])
    try:
        say("Cloning {0}{1} ...".format(address, " at " + ref if ref else ""))
        git("clone", "--recurse-submodules", *(["--branch", ref] if ref else []), "--", address, aside, say=say)
        manifest = read_manifest(aside)
        name = manifest.get("id") if isinstance(manifest, dict) else None
        if not name:
            raise FetchError("its {0} has no id, which names its folder here and is how its comics find it. "
                             "Add \"id\": \"its-name\" to it".format(plugins.MANIFEST))
        try:
            plugins.check_manifest(name, manifest, os.path.isfile(os.path.join(aside, plugins.HOOKS)))
        except plugins.PluginError as error:
            raise FetchError(str(error))
        final = os.path.join(home, name)
        if os.path.exists(final):
            #a plugin from its repository is updated, not installed again; one put in by hand is replaced
            #with the clone, keeping its setup (which is in config/plugin-setup/, not in its folder)
            is_repo = os.path.isdir(os.path.join(final, ".git")) or os.path.isfile(os.path.join(final, ".git"))
            if is_repo:
                raise FetchError("there is a plugin {0} already, from its repository. Update it instead, or "
                                 "remove it first".format(name))
            say("{0} was put in by hand; replacing it with the repository's.".format(name))
            remove_tree(final)
        os.rename(aside, final)
    finally:
        if os.path.exists(aside):
            remove_tree(aside)
    say("Installed {0} as {1}.".format(manifest.get("name") or name, name))
    ready_packages(name, say)
    return name


def update(name, say=print):
    #brought up to the newest of what it follows: its branch, with its tool. one pinned to a tag stays there
    plugin = plugins.load(name, with_hooks=False)
    if not plugin.is_repository:
        raise FetchError("{0} was not installed from a repository, so there is nothing to update it from. "
                         "Remove it and install it from its git address".format(name))
    before = git("rev-parse", "HEAD", cwd=plugin.folder, say=lambda line: None).strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=plugin.folder, say=lambda line: None).strip()
    if branch == "HEAD":
        say("{0} is pinned to {1}, so it is left where it is; install it again to move it.".format(
            name, before[:12]))
    else:
        say("Updating {0} ...".format(name))
        tidy_line_endings(name, plugin.folder, say)
        git("pull", "--ff-only", cwd=plugin.folder, say=say)
    git("submodule", "update", "--init", "--recursive", cwd=plugin.folder, say=say)
    after = git("rev-parse", "HEAD", cwd=plugin.folder, say=lambda line: None).strip()
    #what it now says about itself, which has to still be a plugin of this name
    try:
        plugins.load(name, with_hooks=False)
    except plugins.PluginError as error:
        raise FetchError("its update cannot be used: {0}. Fix it in its repository and update again".format(error))
    say("{0} is {1}.".format(name, "now at " + after[:12] if after != before else "already up to date"))
    ready_packages(name, say)
    return after != before


def tidy_line_endings(name, folder, say):
    #a plugin cloned on windows and copied in has every text file ending its lines in \r\n, which git here
    #counts as a change to each one, and a pull refuses to write over them. changes that are only that are
    #put back as the repository has them; a change of substance is someone's edit, and is never thrown away
    quiet = lambda line: None
    changed = git("status", "--porcelain", "--untracked-files=no", "--ignore-submodules=dirty",
                  cwd=folder, say=quiet).splitlines()
    if not changed:
        return
    #read from the patch itself: --name-only and --stat list a file whose bytes differ, \r or not. a file
    #differing only in its line endings, or in its mode, which a copy from windows changes too, has no hunk
    real, current = [], None
    for line in git("diff", "HEAD", "--ignore-cr-at-eol", "--ignore-submodules=dirty", "--no-color",
                    "--no-ext-diff", cwd=folder, say=quiet).splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[-1]
        elif current and current not in real and (line.startswith("@@") or line.startswith("Binary files")):
            real.append(current)
    if real:
        raise FetchError("{0} has changes made to it here, which an update would write over: {1}. Commit "
                         "them to its repository, or put them back, and update again".format(name, ", ".join(real)))
    say("Its files' line endings were changed when it was copied in ({0} files); putting them back as its "
        "repository has them.".format(len(changed)))
    git("reset", "--hard", "-q", "HEAD", cwd=folder, say=say)


def remove(name, in_use, say=print):
    #in_use is the comics that name it, which keep it: their next runs would fail
    plugin = plugins.load(name, with_hooks=False)
    if in_use:
        raise FetchError("{0} is the scraper of {1}; those comics would stop being updated. Move them to "
                         "another scraper, or remove them, first".format(name, ", ".join(in_use[:5]) +
                                                                       (" and {0} more".format(len(in_use) - 5)
                                                                        if len(in_use) > 5 else "")))
    remove_tree(plugin.folder)
    say("Removed {0}.".format(name))


def remove_tree(folder):
    #git makes its objects read-only, which windows will not delete without being told it may
    def unlock(function, path, ignored):
        os.chmod(path, 0o700)
        function(path)
    #onerror is deprecated from 3.12, which the image runs, in favour of onexc
    shutil.rmtree(folder, **({"onexc": unlock} if sys.version_info >= (3, 12) else {"onerror": unlock}))
