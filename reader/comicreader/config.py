#the reader's settings, all from the environment, so the compose file is the one place they are set
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    #the library, mounted read-only: the folder holding Uncompressed/ and CBZs/, or any folder of archives
    library: str = "/library"
    #where the reader keeps what it owns: progress, the scan, thumbnails
    data: str = "/data"
    #a password for every request, as the scraper's web page has. empty is no password
    password: str = ""
    #how often the whole library is looked over for comics that are new or have grown
    scan_minutes: float = 15.0
    #folders inside the library not to look in, by name, beside every folder starting with a dot
    skip: list = field(default_factory=lambda: ["@Recycle", "@Recently-Snapshot", "#recycle"])
    #the built web page, served at /
    web: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")

    @classmethod
    def from_env(cls):
        made = cls()
        made.library = os.environ.get("READER_LIBRARY", made.library)
        made.data = os.environ.get("READER_DATA", made.data)
        made.password = os.environ.get("READER_PASSWORD", "")
        made.scan_minutes = float(os.environ.get("READER_SCAN_MINUTES", made.scan_minutes))
        if os.environ.get("READER_SKIP"):
            made.skip = [name.strip() for name in os.environ["READER_SKIP"].split(",") if name.strip()]
        made.web = os.environ.get("READER_WEB", made.web)
        return made
