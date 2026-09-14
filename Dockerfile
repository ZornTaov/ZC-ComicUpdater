# Comic mirror for Container Station. Bundles python, chromium and the matching chromedriver so the
# toolchain cannot be broken by a NAS firmware update.
FROM python:3.12-slim

# unbuffered output so progress shows up in the Container Station log while a run is still going
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

COPY mirror_base.py update_comics.py adopt_comic.py web_ui.py web_ui.html /app/

# the web page, when update_comics is started with --web 8080
EXPOSE 8080

# the library is mounted here, and comics are addressed by the relative folder names in their metadata
WORKDIR /library

ENTRYPOINT ["python", "/app/update_comics.py"]
CMD ["--schedule", "03:30"]
