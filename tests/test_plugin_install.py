#a plugin installed from its repository, brought up to date from it and removed, and the python packages
#its plugin.json asks for installed into a venv of its own. the repository is a local one made from the
#example plugin, and the package a wheel made here, so none of this reaches the internet.
import json
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

from comiclib import exits, pluginenv, pluginfetch, plugins
from conftest import console_errors, open_page, read_meta, wait_until
from test_plugins import EXAMPLE, URL, add, install

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(folder, *arguments):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "safe.directory=*"]
                   + list(arguments), cwd=str(folder), check=True, capture_output=True)


def repository(tmp_path, **manifest):
    #the example plugin as a repository of its own, its plugin.json changed as a test needs it
    folder = tmp_path / "source"
    shutil.copytree(EXAMPLE, str(folder))
    path = folder / "plugin.json"
    said = json.loads(path.read_text(encoding="utf-8"))
    said.update(manifest)
    said = {key: value for key, value in said.items() if value is not None}
    path.write_text(json.dumps(said), encoding="utf-8")
    git(folder, "init", "-q", "-b", "main")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    return folder


def wheel(tmp_path, value=42):
    #the smallest package pip will install: one module, and the three files that say what it is
    path = tmp_path / "wheels" / "tinything-1.0-py3-none-any.whl"
    path.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as archive:
        archive.writestr("tinything.py", "VALUE = {0}\n".format(value))
        archive.writestr("tinything-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: tinything\nVersion: 1.0\n")
        archive.writestr("tinything-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: hand\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr("tinything-1.0.dist-info/RECORD", "")
    return str(path)


def plugin_names(config):
    return sorted(os.listdir(str(config / "plugins")))


# ---------------- its id ----------------
def test_a_plugin_whose_id_is_not_its_folders_name_says_to_rename_it(config):
    install(config, name="elsewhere", id="example")
    with pytest.raises(plugins.PluginError, match="its folder has to be named example"):
        plugins.load("elsewhere")


def test_a_plugin_with_no_id_still_loads_from_its_folder(config):
    #put there by hand before plugins had ids
    path = os.path.join(install(config, name="byhand"), "plugin.json")
    with open(path, encoding="utf-8") as f:
        said = json.load(f)
    del said["id"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(said, f)
    assert plugins.load("byhand").name == "byhand"


# ---------------- from its repository ----------------
@needs_git
def test_a_plugin_is_installed_under_its_id_and_nothing_else_is_left(config, tmp_path):
    source = repository(tmp_path, id="my-example")
    assert pluginfetch.install(source.as_uri()) == "my-example"
    assert plugin_names(config) == ["my-example"]
    plugin = plugins.load("my-example")
    assert plugin.is_repository and plugin.view()["env"] is None
    with pytest.raises(pluginfetch.FetchError, match="already"):
        pluginfetch.install(source.as_uri())
    assert plugin_names(config) == ["my-example"]


@needs_git
@pytest.mark.parametrize("manifest, said", [
    ({"id": None}, "has no id"),
    ({"output": "zips"}, "has to be one of"),
])
def test_a_repository_that_is_not_a_usable_plugin_leaves_nothing(config, tmp_path, manifest, said):
    source = repository(tmp_path, **manifest)
    with pytest.raises(pluginfetch.FetchError, match=said):
        pluginfetch.install(source.as_uri())
    assert plugin_names(config) == []


def test_an_address_git_would_take_as_an_option_is_refused(config):
    with pytest.raises(pluginfetch.FetchError, match="not a git address"):
        pluginfetch.install("--upload-pack=touch /tmp/x")
    with pytest.raises(pluginfetch.FetchError, match="not a branch or tag"):
        pluginfetch.install("https://example.com/plugin.git", "--upload-pack=x")


@needs_git
def test_an_update_brings_the_plugin_and_says_when_there_was_nothing(config, tmp_path):
    source = repository(tmp_path)
    pluginfetch.install(source.as_uri())
    assert pluginfetch.update("example") is False
    path = source / "plugin.json"
    said = json.loads(path.read_text(encoding="utf-8"))
    said["about"] = "changed"
    path.write_text(json.dumps(said), encoding="utf-8")
    git(source, "commit", "-q", "-am", "second")
    assert pluginfetch.update("example") is True
    assert plugins.load("example").manifest["about"] == "changed"
    #a venv beside it is this machine's, and git does not count it as a change to the plugin
    os.makedirs(str(config / "plugins" / "example" / pluginenv.VENV))
    open(str(config / "plugins" / "example" / pluginenv.VENV / "x"), "w").close()
    status = subprocess.run(["git", "-c", "safe.directory=*", "status", "--porcelain"], capture_output=True,
                            text=True, cwd=str(config / "plugins" / "example"))
    assert status.stdout == ""


def crlf(path):
    with open(path, "rb") as f:
        held = f.read().replace(b"\r\n", b"\n")
    with open(path, "wb") as f:
        f.write(held.replace(b"\n", b"\r\n"))


@needs_git
def test_a_plugin_copied_in_from_windows_still_updates_but_an_edit_is_kept(config, tmp_path):
    #cloned on windows and copied into the container, every file ends its lines in \r\n, which git there
    #counts as changes that a pull will not write over
    source = repository(tmp_path)
    pluginfetch.install(source.as_uri())
    installed = config / "plugins" / "example"
    git(installed, "config", "core.autocrlf", "false")
    crlf(str(installed / "plugin.json"))
    crlf(str(installed / "plugin.py"))
    said = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
    said["about"] = "changed"
    (source / "plugin.json").write_text(json.dumps(said), encoding="utf-8")
    git(source, "commit", "-q", "-am", "second")
    lines = []
    assert pluginfetch.update("example", lines.append) is True
    assert any("line endings were changed" in line for line in lines)
    assert plugins.load("example").manifest["about"] == "changed"
    #an edit made here is someone's, and is never thrown away
    with open(str(installed / "plugin.py"), "a", encoding="utf-8") as f:
        f.write("# mine\n")
    with pytest.raises(pluginfetch.FetchError, match="changes made to it here.*plugin.py"):
        pluginfetch.update("example")
    assert "# mine" in (installed / "plugin.py").read_text(encoding="utf-8")


def test_a_plugin_put_in_by_hand_cannot_be_updated(config):
    install(config)
    with pytest.raises(pluginfetch.FetchError, match="not installed from a repository"):
        pluginfetch.update("example")


@needs_git
def test_installing_from_git_replaces_a_plugin_put_in_by_hand(config, tmp_path):
    #a plugin copied in by hand can be replaced by installing it from its repository, so the person
    #does not have to remove it first and lose what they had
    install(config)
    plugin = plugins.load("example")
    assert not plugin.is_repository
    source = repository(tmp_path)
    said = []
    pluginfetch.install(source.as_uri(), say=said.append)
    assert any("put in by hand" in line for line in said)
    plugin = plugins.load("example")
    assert plugin.is_repository
    assert plugin_names(config) == ["example"]


@needs_git
def test_installing_from_git_over_a_manual_plugin_keeps_its_setup(config, tmp_path):
    from comiclib import pluginsetup
    install(config, setup=[{"key": "token", "type": "secret", "label": "Token"}])
    pluginsetup.write("example", {"token": "kept-value"})
    source = repository(tmp_path, setup=[{"key": "token", "type": "secret", "label": "Token"}])
    pluginfetch.install(source.as_uri())
    assert pluginsetup.stored("example") == {"token": "kept-value"}


def test_a_plugin_a_comic_uses_is_not_removed(config):
    install(config)
    with pytest.raises(pluginfetch.FetchError, match="scraper of Uncompressed/MyComic"):
        pluginfetch.remove("example", ["Uncompressed/MyComic"])
    pluginfetch.remove("example", [])
    assert plugin_names(config) == []


# ---------------- its packages ----------------
def test_its_packages_are_installed_once_and_again_for_a_new_python(config, tmp_path):
    folder = install(config, install={"pip": [wheel(tmp_path)]})
    said = []
    plugin = plugins.load("example").ready(said.append)
    assert plugin.python != sys.executable and plugin.view()["env"] == "ready"
    found = subprocess.run([plugin.python, "-c", "import tinything, selenium; print(tinything.VALUE)"],
                           capture_output=True, text=True)
    assert found.stdout.strip() == "42", found.stderr
    #ready already: nothing is built
    said.clear()
    plugins.load("example").ready(said.append)
    assert said == []
    #a new image with a newer python: the venv is built again, and says why
    stamp = os.path.join(folder, pluginenv.VENV, pluginenv.STAMP)
    with open(stamp, encoding="utf-8") as f:
        built = json.load(f)
    with open(stamp, "w", encoding="utf-8") as f:
        json.dump(dict(built, python="3.0"), f)
    assert plugins.load("example").view()["env"] == "to build"
    plugins.load("example").ready(said.append)
    assert any("installed for python 3.0" in line for line in said)


def test_a_plugin_run_uses_its_own_python(library, config, tmp_path):
    install(config, output="chapter-cbz", install={"pip": [wheel(tmp_path)]})
    assert add(library).returncode == exits.OK
    run = read_meta(library / "Uncompressed" / "MyComic")["history"]["runs"][-1]
    assert os.path.dirname(os.path.dirname(run["argv"][0])).endswith(pluginenv.VENV)


def test_packages_that_will_not_install_fail_the_run_and_say_so(library, config, tmp_path):
    install(config, install={"pip": [str(tmp_path / "no-such.whl")]})
    done = add(library)
    assert done.returncode == exits.TOOL_FAILED
    assert "installing its packages failed" in done.stdout


def test_a_program_it_needs_that_is_not_here_is_named(library, config):
    install(config, needs=["no-such-program-anywhere"])
    done = add(library)
    assert done.returncode == exits.TOOL_FAILED
    assert "needs no-such-program-anywhere, which this image does not have" in done.stdout


# ---------------- the web page ----------------
def shown(browser, element_id):
    return browser.execute_script(
        "const e = document.getElementById(arguments[0]); return !!e && e.getClientRects().length > 0", element_id)


@pytest.mark.browser
@needs_git
def test_the_plugins_dialog_installs_one_and_lists_it_when_done(library, config, web, browser, tmp_path):
    source = repository(tmp_path)
    page = web(env={pluginfetch.ALLOW: "yes"})
    open_page(browser, page.base + "/")
    browser.find_element("id", "open-plugins").click()
    wait_until(lambda: "No plugins yet" in browser.find_element("id", "pl-list").text)
    assert not shown(browser, "pl-why-not")
    browser.find_element("id", "pl-url").send_keys(source.as_uri())
    browser.find_element("id", "pl-install").click()
    wait_until(lambda: "Queued" in browser.find_element("id", "pl-msg").text, why="the install was never queued")
    #read again by itself once the job is done, with the dialog still open
    wait_until(lambda: "from its repository" in browser.find_element("id", "pl-list").text, limit=120,
               why="the installed plugin never showed")
    assert browser.find_elements("css selector", "[data-plugin-update='example']")
    assert not console_errors(browser)


@pytest.mark.browser
def test_the_plugins_dialog_says_why_it_cannot_install(library, config, web, browser):
    install(config)
    page = web(env={pluginfetch.ALLOW: ""})
    open_page(browser, page.base + "/")
    browser.find_element("id", "open-plugins").click()
    wait_until(lambda: shown(browser, "pl-why-not"))
    assert "MIRROR_WEB_PASSWORD" in browser.find_element("id", "pl-why-not").text
    assert not browser.find_element("id", "pl-install").is_enabled()
    assert "put in by hand" in browser.find_element("id", "pl-list").text

@needs_git
def test_the_page_installs_only_behind_a_password_or_when_told_it_may(library, config, web, tmp_path):
    source = repository(tmp_path)
    page = web(env={pluginfetch.ALLOW: ""})
    code, answer = page.call("/api/plugins")
    assert answer["may_install"] is False and "MIRROR_WEB_PASSWORD" in answer["why_not"]
    code, answer = page.call("/api/plugins/install", {"url": source.as_uri()})
    assert code == 403
    page.stop()

    page = web(env={pluginfetch.ALLOW: "yes"})
    code, answer = page.call("/api/plugins/install", {"url": source.as_uri()})
    assert code == 200, answer
    assert page.wait_idle(120)
    code, answer = page.call("/api/plugins")
    assert [plugin["name"] for plugin in answer["plugins"]] == ["example"]
    assert answer["plugins"][0]["repository"] is True
    code, answer = page.call("/api/plugins/remove", {"name": "example"})
    assert code == 200 and page.wait_idle(120)
    assert plugin_names(config) == []
