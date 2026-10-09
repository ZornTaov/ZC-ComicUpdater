#python -m comicreader: the server, on READER_PORT (8082 by default)
import os

import uvicorn

from comicreader.app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.environ.get("READER_HOST", "0.0.0.0"),
                port=int(os.environ.get("READER_PORT", "8082")), log_level="warning")
