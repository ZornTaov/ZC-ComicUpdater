#python -m comicreader: the server, on READER_PORT (8082 by default)
import os

import uvicorn

from comicreader.app import create_app
from comicreader.config import Config

if __name__ == "__main__":
    config = Config.from_env()
    port = int(os.environ.get("READER_PORT", "8082"))
    #uvicorn's own lines are left out unless asked for: at info it logs every page and thumbnail fetched,
    #hundreds a chapter, which buries the reader's own few lines below. info or debug is for chasing a fault
    level = os.environ.get("READER_LOG_LEVEL", "warning").lower()
    print("comic reader on port {0}: library {1}, data {2}, {3}, scanning every {4:g} minutes".format(
        port, config.library, config.data, "password set" if config.password else "no password",
        config.scan_minutes), flush=True)
    uvicorn.run(create_app(config), host=os.environ.get("READER_HOST", "0.0.0.0"), port=port, log_level=level)
