#the page's log is everything update_comics prints, kept line by line. print writes a line's text and its
#newline as two calls, so two threads printing at once - a request queueing a job while the worker starts
#another - once came out as one line, "Queued: ...Checking ...", on the page and in the container log alike.
import io
import threading

from comiclib.web.jobs import LogTee


def interleaved(tee):
    #the exact order that glued two lines together: each thread's text, then each one's newline
    first_text, first_done, second_done = threading.Event(), threading.Event(), threading.Event()

    def queueing():
        tee.write("Queued: Check http://example.com/comic/5")
        first_text.set()
        second_done.wait(5)
        tee.write("\n")
        first_done.set()

    def checking():
        first_text.wait(5)
        tee.write("Checking http://example.com/comic/5")
        tee.write("\n")
        second_done.set()

    threads = [threading.Thread(target=queueing), threading.Thread(target=checking)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)


def test_two_threads_printing_at_once_keep_their_lines_apart():
    out = io.StringIO()
    tee = LogTee(out)
    interleaved(tee)
    lines = [line for _, _, line in tee.since(0)[0]]
    assert sorted(lines) == ["Checking http://example.com/comic/5", "Queued: Check http://example.com/comic/5"]
    assert sorted(out.getvalue().splitlines()) == sorted(lines), "the container log should not glue them either"


def test_a_line_with_no_newline_reaches_the_output_when_flushed():
    out = io.StringIO()
    tee = LogTee(out)
    tee.write("still going")
    assert out.getvalue() == ""
    tee.flush()
    assert out.getvalue() == "still going"
    #and the page has it once the line is finished
    tee.write("...done\n")
    assert [line for _, _, line in tee.since(0)[0]] == ["still going...done"]
    assert out.getvalue() == "still going...done\n"
    assert not tee.partial and not tee.unsent, "nothing should be kept for a thread with nothing half written"
