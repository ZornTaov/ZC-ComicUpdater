"""What the scripts share.

mirror_base, chapters, update_comics, adopt_comic and web_ui are the commands; this is what more than one
of them needs to agree on - where the settings are, what makes two filenames one page, how the metadata
is read and written, how an archive is packed - kept in one place so that the answer to "what does a
reader see here" cannot drift between a comic kept in one archive and one kept in chapters.

Standard library only, beyond the requests and selenium the scripts already need: a new dependency
means rebuilding the container.
"""
