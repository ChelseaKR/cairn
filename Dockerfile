# Nothing here is container-specific — cairn has no runtime dependencies to
# vendor — so the image is a straight copy of the source tree plus an
# entrypoint. See docs/deployment.md, "Running it in a container", for the
# operational half (why --host 0.0.0.0, how to publish the port, where the
# reverse proxy goes); tests/test_container.py holds this file and that
# page's fenced block to the same directives so the two cannot drift apart.
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && \
    python -m cairn index

# `cairn index` above runs as root, before this: it needs to write
# .cairn/index.json into the image, and pip needs root to install into the
# system site-packages in the first place. Nothing after this line needs
# root — cairn serve writes nothing at all in its default configuration —
# so the process that actually answers a network request does not have it.
RUN useradd --no-create-home --shell /usr/sbin/nologin cairn
USER cairn

EXPOSE 8765
ENTRYPOINT ["cairn", "serve", "--host", "0.0.0.0"]
