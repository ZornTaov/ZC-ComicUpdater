#the example plugin's own functions. each one is optional, and each replaces the updater's default of the
#same name; a plugin that needs none of them has no plugin.py at all. this file is run by the process that
#runs one of the plugin's comics, and nowhere else - never by the web page.
import re


def chapter_order(labels):
    #the order chapters the program wrote are taken in. the default sorts their names, numbers as numbers;
    #this one goes by the chapter's number alone, so "Chapter 10 (part 2)" still follows "Chapter 9"
    def number(label):
        found = re.search(r"(\d+(?:\.\d+)?)", label)
        return (float(found.group(1)) if found else float("inf"), label)
    return sorted(labels, key=number)


def remember(state, taken):
    #where the program got to, which its next command is built from: plugin.json's command names it as
    #{last_chapter}. taken is what this run took in: {"pages": [...], "chapters": [...], "skipped": [...]}.
    #a chapter fetched again and not taken in is still where the program got to
    newest = (taken["chapters"] or taken["skipped"])[-1:] or [state.get("last_chapter")]
    if newest[0]:
        state["last_chapter"] = newest[0]
    return state
