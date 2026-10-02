#a small web page for update_comics: watch what a run is doing, start updates, add new comics, stop things.
#standard library only, so the container needs nothing new. started by update_comics.py --web PORT. #V 1.0
#
#the page is the web_page folder; what serves it is in comiclib.web, one module for each part. everything this held
#is still reachable here under its old name.
from comiclib.web.adding import clean_folder, default_cbz, parse_entries, under_root  # noqa: F401
from comiclib.web.edits import (clean_settings, editable, fix_chapter, insert_page, max_edits,  # noqa: F401
                                save_config, save_settings, try_chapter_list)
from comiclib.web.elementpaths import (element_file, element_paths_path, element_settings,  # noqa: F401
                                       kinds, save_elements, shipped, shipped_paths)
from comiclib.web.jobs import Job, LogTee, Runner, remember_listing, split_into_chapters  # noqa: F401
from comiclib.web.server import make_handler, page_folder, page_part, start  # noqa: F401
from comiclib.web.views import (comic_detail, comic_view, config_view, find_comic, index_pages,  # noqa: F401
                                is_running, job_view, library_view, read_metadata, walked_pages)



