# The comic reader, as an image of its own beside the scraper's. Built from the repo root, so it can take
# comiclib - the scraper's own rules for what a page is and the order pages read in - rather than a copy:
#
#     docker build -f reader/Dockerfile -t comic-reader:0.1 .
#
# The web page is built here too, so nothing but docker is needed on the machine doing the building.

FROM node:22-slim AS web
WORKDIR /web
COPY reader/web/package.json reader/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY reader/web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    READER_LIBRARY=/library \
    READER_DATA=/data \
    READER_WEB=/app/web \
    READER_PORT=8082

# copied on its own so changing the code does not throw away the cached pip layer
COPY reader/requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY comiclib/ /app/comiclib/
COPY reader/comicreader/ /app/comicreader/
COPY --from=web /web/dist /app/web

# what the reader keeps: progress, its record of the library, covers. writable by anyone, since the
# container runs as the library's owner rather than root
RUN mkdir -p /data && chmod 0777 /data

WORKDIR /app
EXPOSE 8082
CMD ["python", "-m", "comicreader"]
