# Comic mirror for any docker host. Bundles python, chromium and the matching chromedriver so the toolchain
# cannot be broken by an update to the host, and the scripts themselves, so the image runs on its own with
# nothing but a library mounted. Published as ghcr.io/zorntaov/comics-updater by .github/workflows/images.yml;
# build it yourself from the repo root with `docker build -t comics-updater:local .`
#
# Mounting a folder over /app replaces the scripts baked in here with that folder's, which is how to run
# edits without a new image: change a file in that folder, restart the container. See the wiki's Docker page.
FROM python:3.12-slim

# unbuffered output so progress shows up in the container's log while a run is still going
ENV PYTHONUNBUFFERED=1 \
    MIRROR_BROWSER_BINARY=/usr/bin/chromium \
    MIRROR_DRIVER_BINARY=/usr/bin/chromedriver \
    MIRROR_BROWSER_ARGS=--no-sandbox

# chromium-driver comes from the same repository as chromium, so the two versions always agree
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        tzdata \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# copied on its own so editing a script does not throw away the cached pip layer
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

# the program: the six commands, the page, and the package they all share. named one by one rather than
# with a wildcard, so nothing else that happens to sit beside them ends up in a published image
COPY mirror_base.py chapters.py update_comics.py adopt_comic.py web_ui.py run_plugin.py /app/
COPY web_page/ /app/web_page/
COPY comiclib/ /app/comiclib/

# settings and element paths are written here: mount a folder over it to keep them across a new container.
# writable by anyone, since the container runs as the library's owner rather than as root, and the web
# page has to be able to save them even when nothing is mounted
RUN mkdir -p /app/config/index && chmod -R 0777 /app/config

# chrome writes a profile under $HOME as it starts, and exits at once if it cannot. run as the library's
# owner, as the compose file does, the user has no home of its own and $HOME is /, which only root can
# write. /tmp can be written by anyone, and nothing there needs to outlive the container
ENV HOME=/tmp

# the web page, when update_comics is started with --web 8080
EXPOSE 8080

# the library is mounted here, and comics are addressed by the relative folder names in their metadata
WORKDIR /library

ENTRYPOINT ["python", "/app/update_comics.py"]
CMD ["--schedule", "03:30"]
