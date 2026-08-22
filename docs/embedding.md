# Embedding Cairn in an agency's own site

`cairn serve`'s default page carries `frame-ancestors 'none'` and sends no
CORS headers at all, so by default nothing can put it in an `<iframe>` and
no other origin's JavaScript can call its API. That is correct for a
standalone deployment and unchanged unless an operator asks for something
different — see `SECURITY.md` and `docs/deployment.md`.

An agency that wants Cairn reachable *from* their existing site — rather
than as its own destination — has two options, and they are separate flags
because they are separate questions: "can this page go in a frame on your
site" is not "can your site's own script call this API directly."

## Option 1: iframe the page as-is

The simplest integration: put the whole served page — chat form, transcript,
accessibility behaviour and all — inside an `<iframe>` on an existing page.
Nothing to build; the interface is already there.

```console
$ cairn serve --allow-embed https://agency.example.gov
```

```html
<iframe
  src="https://cairn.example.gov/"
  title="Ask a question about benefits"
  style="width: 100%; height: 32rem; border: 1px solid #ccc;">
</iframe>
```

`--allow-embed` is repeatable for more than one origin. Each origin must be
exact — scheme, host, and port — and each one that is not on the list still
gets `frame-ancestors 'none'`, i.e. refused, the same as before this
existed. There is no wildcard: an operator names the specific site or sites
trusted to embed the page, not "anyone who tries."

This changes exactly one thing about the page's Content-Security-Policy —
the `frame-ancestors` directive. `default-src 'none'`, `style-src 'self'`,
`script-src 'self'`, and `connect-src 'self'` are unaffected: the embedded
page still loads nothing from outside itself.

## Option 2: call the JSON API from your own page

For a custom-styled integration — the agency's own widget, not an iframe of
Cairn's own page — call `POST /ask` directly from the agency site's own
JavaScript and render the answer in your own markup. This needs CORS,
because a browser refuses a cross-origin `fetch()` until the server says the
calling origin is allowed to see the response:

```console
$ cairn serve --cors-origin https://agency.example.gov
```

```js
async function askCairn(question) {
  const response = await fetch("https://cairn.example.gov/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, lang: "en" }),
  });
  return response.json(); // { answer, sources, ... } or { error }
}
```

No cookies, no session, nothing stored in the browser between calls — Cairn
has none to send, so there is nothing to opt into on the client side either.
If the server also has `--auth-token`/`CAIRN_AUTH_TOKEN` set (see
`docs/deployment.md`), add the header to the same request:

```js
headers: {
  "Content-Type": "application/json",
  "Authorization": "Bearer " + token,
},
```

`--cors-origin` is repeatable, exact-origin-only, and never wildcarded — the
same shape as `--allow-embed`, and for the same reason: a bearer token in
the `Authorization` header cannot be paired with a wildcarded
`Access-Control-Allow-Origin` under the CORS spec, and an explicit allow-list
is also simply what "an agency's own site" means, rather than "any site
that asks." An origin not on the list gets no `Access-Control-*` headers at
all — a browser refuses the fetch exactly as it always has.

The server also answers the CORS preflight (`OPTIONS`) request a browser
sends ahead of a `POST` with a JSON body, for any origin on the
`--cors-origin` list. The preflight is deliberately not gated by
`--auth-token`: a preflight request never carries the `Authorization` header
the real request would (that is what it exists to negotiate beforehand), so
gating it would refuse every preflight and the real, authenticated request
behind it would never be sent.

## The two flags are independent

`--allow-embed` only widens `frame-ancestors`; it does not enable CORS.
`--cors-origin` only enables CORS; it does not widen `frame-ancestors`. Set
both if an integration needs both — e.g. an iframe whose own script also
calls the API directly rather than relying on the framed page's UI — or
either alone for the one form of integration actually needed. Neither
implies the other, on purpose: a page allowed to frame Cairn is not thereby
allowed to script against its API, and the reverse.

## Still true either way

Nothing here changes what Cairn answers, what it logs (nothing about a
question, ever — see the `cairn/server.py` module docstring), or the
"grounded or silent" contract described in `README.md`. `--allow-embed` and
`--cors-origin` are access controls on top of the same server, the same
engine, and the same refusal behaviour — an agency's own site gets exactly
the answers (and exactly the refusals) the standalone page would have given.
