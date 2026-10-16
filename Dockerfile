# syntax=docker/dockerfile:1

# Comic mirror for any docker host. Bundles python, chromium and the matching chromedriver so the toolchain
# cannot be broken by an update to the host, and the scripts themselves, so the image runs on its own with
# nothing but a library mounted. Published as ghcr.io/zorntaov/comics-updater by .github/workflows/images.yml;
# build it yourself from the repo root with `docker build -t comics-updater:local .`
#
# Mounting a folder over /app replaces the scripts baked in here with that folder's, which is how to run
# edits without a new image: change a file in that folder, restart the container. See the wiki's Docker page.
# python packages do not depend on chromium: either can change without rebuilding the other
FROM python:3.12-slim AS python-deps
COPY requirements.txt /build/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --prefix=/install -r /build/requirements.txt

FROM python:3.12-slim

# unbuffered output so progress shows up in the container's log while a run is still going
ENV PYTHONUNBUFFERED=1 \
    MIRROR_BROWSER_BINARY=/usr/bin/chromium \
    MIRROR_DRIVER_BINARY=/usr/bin/chromedriver \
    MIRROR_BROWSER_ARGS=--no-sandbox

# chromium-driver comes from the same repository as chromium, so the two versions always agree. git is for
# scraper plugins, which are installed and updated from their repositories, their programs as submodules
# cache mounts stay out of the image; docker-clean would otherwise discard the downloaded packages
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        git \
        tzdata \
        ca-certificates

# settings and element paths are written here: mount a folder over it to keep them across a new container.
# each comic's run log goes in logs/ beside it, mounted or not. both writable by anyone, since the container
# runs as the library's owner rather than as root, and /app itself is root's: with only config/ mounted,
# a run as any other user could not make logs/ and every log said permission denied
RUN mkdir -p /app/config/index /app/logs && chmod -R 0777 /app/config /app/logs

COPY --link --from=python-deps /install/ /usr/local/
COPY --link requirements.txt /app/

# linked copies keep the page, scripts and shared package as reusable layers even when a sibling changes.
# name the inputs rather than using a wildcard: the surrounding folder can be a working comic library
COPY --link web_page/ /app/web_page/
COPY --link comiclib/ /app/comiclib/
COPY --link mirror_base.py chapters.py update_comics.py adopt_comic.py web_ui.py run_plugin.py /app/

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
