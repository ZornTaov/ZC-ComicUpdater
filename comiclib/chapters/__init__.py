"""Everything about a comic's chapters, which chapters.py is the command for.

index        the record of which page is which, and walking a comic for it
align        lining that record up against the files on disk
links        telling one page's address from another's
archive_page reading a comic's archive page for where its chapters start
addresses    chapters from the comic's own addresses, or from a list of them
chapterlist  the chapter list a comic keeps, corrected by hand and saved
packing      one archive per chapter, and the single archive written afresh
pageops      fetching, numbering and putting in pages
"""
