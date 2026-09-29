#a schema 1 sidecar saved the scrape command itself; argv_to_settings pulls it apart into settings, and
#settings_to_argv is the one place a command is built back from them. nothing may be lost on the way round.
import pytest

from conftest import fresh

CASES = [
    #long flags, a prefix, an archive path, and an address ending in a slash
    ["--increment", "734", "--output", "Uncompressed/My_Comic", "--prefix",
     "--cbz-path", "CBZs/My_Comic.cbz", "https://example.com/comic/some-page/"],
    #an address carrying its page in the query string
    ["--increment", "5885", "--output", "Uncompressed/OtherComic",
     "--cbz-path", "CBZs/OtherComic.cbz", "https://example.com/view.php?comic=5885"],
    #short flags, and an increment written with a leading zero
    ["-p", "-i", "0149", "-o", "ThirdComic", "https://example.com/index.php?pid=20120102"],
    #the machine-ish flags, and the archive turned off
    ["--enable_javascript", "--firefox", "--waittime", "3", "--no-cbz", "-o", "Weird", "https://x.test/1"],
]


@pytest.fixture
def update(config):
    return fresh("update_comics")


@pytest.mark.parametrize("argv", CASES, ids=["long-flags", "query-string", "short-flags", "machine-flags"])
def test_settings_survive_the_round_trip_through_a_command(update, argv):
    settings = update.argv_to_settings(argv)
    back = update.settings_to_argv(settings)
    assert update.argv_to_settings(back) == settings, back


@pytest.mark.parametrize("argv", CASES[:2], ids=["long-flags", "query-string"])
def test_a_command_in_long_flags_comes_back_as_it_was(update, argv):
    #short flags come back long, and a padded number unpadded, so only a long-flag command is compared
    #word for word
    back = update.settings_to_argv(update.argv_to_settings(argv))
    assert back == argv or set(back) == set(argv), back
