# Running `cairn serve` past a laptop demo

`cairn serve`'s default is a loopback-only server with no auth, no TLS, and
no rate limiting — see `SECURITY.md`. That default is correct for what it
was built for: a local demo, one operator, one machine. It is not correct
for an agency that wants a small internal tool other people on the network
can reach.

This page is for the operator who has decided to move past the default. It
covers what `cairn` itself now does (bearer-token auth, a rate limiter) and,
more importantly, what it still doesn't — the parts that have to come from
outside this process, because they are not things a `pip install`-free
stdlib tool should try to own.

## What `cairn serve` adds, opt-in

Two flags, both off unless you set them:

```console
$ cairn serve --auth-token "$(openssl rand -hex 32)" --rate-limit 60
```

- **`--auth-token TOKEN`** (or the `CAIRN_AUTH_TOKEN` environment variable):
  every request must carry `Authorization: Bearer TOKEN`, checked with a
  constant-time comparison. A request without it gets `401` with a
  `WWW-Authenticate: Bearer` header. Prefer the environment variable over the
  flag on a real deployment — a flag is visible to anything that can read
  `/proc` on the same machine (`ps`, another user's shell), an environment
  variable read once at startup is not.
- **`--rate-limit N`**: at most `N` requests per minute from a single client
  address, past which the server answers `429` with `Retry-After: 60`. It is
  a fixed window per client IP, in memory, per process — restarting the
  server resets every client's count. This is a blunt instrument against one
  client hammering the endpoint, not a fairness scheduler or a defense
  against a distributed flood.

Both apply to every route — the page, the static assets, `/ask` — through
one check at the top of the request handler, so there is nowhere in the
server that quietly skips it.

Read `cairn/network.py`'s module docstring for the implementation notes; this
page is the operational half.

## What this is not

- **Not TLS.** `cairn serve` speaks plain HTTP. It has no certificate
  handling and never will — that is a solved problem one process shouldn't
  reinvent. Terminate TLS in front of it (below).
- **Not a login system.** The bearer token is one shared secret for the
  whole deployment, checked per request. It is *service* protection —
  right for a machine caller, or a small internal tool behind its own
  network boundary — not identity for individual end users. If you need
  per-user accounts, sessions, or audit trails tied to a person, that is a
  different piece of software in front of this one.
- **Not a firewall.** The rate limiter slows down one noisy client; it does
  not defend against a real distributed flood, and `SECURITY.md` already
  scopes denial-of-service against your own server as out of scope for a
  vulnerability report.
- **Not `X-Forwarded-For`-aware.** The rate limiter keys on the direct TCP
  peer address. Put a reverse proxy in front and every request arrives from
  the proxy's address, and the limit becomes "N requests/minute across all
  your real clients combined," not per real client. If that matters for your
  deployment, put the limiting in the proxy instead and leave `--rate-limit`
  unset.
- **Not secret rotation, log review, or incident response.** Those are
  practices, not flags. `SECURITY.md` covers how to report a vulnerability;
  what you do with a leaked token is a decision for whoever operates the
  deployment.

## A reverse proxy in front

The supported shape is `cairn serve` bound to loopback, with a real HTTP
server in front doing TLS and forwarding to it. Two examples; both terminate
TLS and forward everything else through unchanged.

**Caddy** (`Caddyfile`), because it gets a certificate for you with no
separate step:

```
cairn.example.gov {
    reverse_proxy 127.0.0.1:8765
}
```

**nginx**, where you manage the certificate yourself (e.g. via certbot):

```nginx
server {
    listen 443 ssl;
    server_name cairn.example.gov;

    ssl_certificate     /etc/letsencrypt/live/cairn.example.gov/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cairn.example.gov/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
    }
}
```

Either way, `cairn serve` itself keeps binding `127.0.0.1` — it is the proxy
that has a public address, not the Cairn process.

## Running it as a service

A `systemd` unit keeps it running and restarts it if it dies. Adjust the
paths and the corpus location to your deployment; `CAIRN_AUTH_TOKEN` is set
in an `EnvironmentFile` so the secret never appears in `systemctl status` or
process listings:

```ini
# /etc/systemd/system/cairn.service
[Unit]
Description=Cairn chat interface
After=network.target

[Service]
Type=simple
User=cairn
WorkingDirectory=/opt/cairn
EnvironmentFile=/etc/cairn/cairn.env
ExecStart=/opt/cairn/.venv/bin/cairn serve --rate-limit 60
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```console
# /etc/cairn/cairn.env  (chmod 600, owned by the cairn user)
CAIRN_AUTH_TOKEN=<your generated token>
```

```console
$ sudo systemctl enable --now cairn
```

## Running it in a container

Nothing here is container-specific — `cairn` has no runtime dependencies to
vendor — so the image (the real `Dockerfile` at the repository root;
`tests/test_container.py` holds this block to the same directives) is a
straight copy of the source tree plus an entrypoint:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && \
    python -m cairn index
RUN useradd --no-create-home --shell /usr/sbin/nologin cairn
USER cairn
EXPOSE 8765
ENTRYPOINT ["cairn", "serve", "--host", "0.0.0.0"]
```

`cairn index` at build time bakes an index for whatever corpus is in the
build context — the bundled demo corpus, unless you replace `corpus/` with
your own before building — so the image is immediately runnable rather than
refusing on first request for want of one. It runs before `useradd`/`USER`
because it and `pip install` both need to write into the image, which only
root can do; nothing after that line needs root, because `cairn serve`
writes nothing at all in this configuration.

`--host 0.0.0.0` is required inside a container — the default `127.0.0.1`
would only be reachable from inside the container's own network namespace,
which is never what you want when a container's whole job is to be reached
from outside it. Pass the auth token and rate limit at run time rather than
baking them into the image:

```console
$ docker run -d -p 127.0.0.1:8765:8765 \
    -e CAIRN_AUTH_TOKEN="$(openssl rand -hex 32)" \
    cairn serve --host 0.0.0.0 --rate-limit 60
```

Publishing the container port to `127.0.0.1` on the host (as above) and
putting the reverse proxy from the previous section in front of *that* keeps
the same TLS story as running `cairn` directly on the host.

A prebuilt image of the bundled demo corpus, published from a tagged
release, is at `ghcr.io/chelseakr/cairn` — see
[`docs/release.md`](release.md) for what "published" means here and how
current that claim is.

## Checklist

Before pointing a real network at `cairn serve`:

- [ ] A reverse proxy terminates TLS; `cairn serve` itself still binds
      loopback (or, in a container, is reached only through the proxy).
- [ ] `CAIRN_AUTH_TOKEN` is set from a secret store or an `EnvironmentFile`,
      not typed into a shell history.
- [ ] `--rate-limit` is set to a number you've actually thought about, or
      deliberately left unset because the proxy already does this.
- [ ] Whoever holds the token knows what "leaked" means for a shared-secret
      deployment — a new token requires a restart, not a reset flow, because
      there is no per-user account to revoke.
- [ ] The corpus behind this server is one you're comfortable a token holder
      can query in full; auth controls who can ask, not what a legitimate
      question can surface from within the corpus.
