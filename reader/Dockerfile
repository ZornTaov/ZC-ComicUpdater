# syntax=docker/dockerfile:1

# ZornCoMix Reader, as an image of its own beside the scraper's. Built from the repo root, so it can take
# comiclib - the scraper's own rules for what a page is and the order pages read in - rather than a copy.
# Published as ghcr.io/zorntaov/zcm-reader by .github/workflows/images.yml; to build it yourself:
#
#     docker build -f reader/Dockerfile -t zcm-reader:local .
#
# The web page is built here too, so nothing but docker is needed on the machine doing the building.

# the output is static files, identical for both image architectures; do not compile them under qemu
FROM --platform=$BUILDPLATFORM node:22-slim AS web
WORKDIR /web
COPY --link reader/web/package.json reader/web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm ci --no-audit --no-fund
COPY --link reader/web/ ./
RUN npm run build

FROM python:3.12-slim AS python-deps
COPY reader/requirements.txt /build/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --prefix=/install -r /build/requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    READER_LIBRARY=/library \
    READER_DATA=/data \
    READER_WEB=/app/web \
    READER_PORT=8082

# what the reader keeps: progress, its record of the library, covers. writable by anyone, since the
# container runs as the library's owner rather than root
RUN mkdir -p /data && chmod 0777 /data

COPY --link --from=python-deps /install/ /usr/local/
COPY --link reader/requirements.txt /app/
# the large static player stays reusable when only the python server or shared package changes
COPY --link --from=web /web/dist /app/web
COPY --link comiclib/ /app/comiclib/
COPY --link reader/comicreader/ /app/comicreader/

WORKDIR /app
EXPOSE 8082
CMD ["python", "-m", "comicreader"]
