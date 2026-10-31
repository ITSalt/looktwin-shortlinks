# looktwin-shortlinks

A one-file short-link service with a click counter, written by **glitchfox**, an AI agent on the open board getpostingboard.dev (board task #966, posts 6c958cf0 and bb0541be). Python standard library only, one SQLite file.

Deployed at https://go.itsalt.ru (v3, commit fa845fc0).

## What it does
- `POST /api/links` with `Authorization: Bearer <token>` and a JSON body `{"url": "...", "code": "..."}` (code optional) creates a short link. It answers `201 {"code", "short"}`.
  - With no `code`, it generates a random 7-character one.
  - A custom code is 3–32 characters of `A–Z a–z 0–9 _ -`, and `api` is reserved. A code already in use gives `409`.
- `GET /<code>` answers `302` to the stored URL and records one click: the UTC time and a cleaned referrer.
- `GET /api/links/<code>/stats` (same token) gives the URL, the click count, clicks by UTC day and the top 10 referrers, for example:
  ```json
  {"url": "https://ex.com/a", "clicks": 4, "by_day": {"2026-10-30": 4},
   "top_referrers": [["https://a.example:8443", 3], ["https://b.example", 1]]}
  ```
- Errors: `401` without the right token, `400` for a bad body, URL or code (including JSON nested too deep to parse), `404` for an unknown code or path.
- A client that stops sending is cut off after 10 seconds.

## What it keeps
- Table `links(code, url)` and table `clicks(code, ts, referrer)`. Nothing else: no IP addresses, no user agents, no cookies.
- From the referrer only the origin is kept: `scheme://host[:port]`.
  - Default ports are dropped, so `https://a.example:443/x` is stored as `https://a.example`. Other ports stay, for example `https://a.example:8443`.
  - The path, `;parameters`, query string, fragment, user name and password are never stored: any of them can carry a token (`/reset/SECRET`, `;jsessionid=...`).
  - A referrer that is not http or https, or whose host is longer than 253 characters or has non-printable bytes, is not stored: the click is counted without a referrer.
- The server prints no request log and no tracebacks.

## URL rule
A URL is accepted only if all of these hold:
- the scheme is `http` or `https`;
- it has a host;
- it is at most 2048 characters;
- it is **printable ASCII only** (characters 0x21–0x7e).

The last rule is glitchfox's addition beyond the task: a CR/LF or a non-Latin-1 character in the stored URL would otherwise split or break the `Location` header of the redirect (header injection, for example a forged `Set-Cookie`). Non-ASCII addresses have to be sent already percent-encoded or in punycode.

## Run
```
SHORTY_TOKEN='a long random secret' python3 shorty.py --db shorty.db --host 127.0.0.1 --port 8080 --base https://s.example
```
- All four options are required.
- `--base` is the public address used in the `short` field.
- Without `SHORTY_TOKEN`, or with an empty one, the program exits with code 2 and does not start.
- Put it behind a reverse proxy that terminates TLS. The service itself speaks plain HTTP.

## Tests
```
python3 -m unittest -q
```
The tests start the server on a random local port and need a writable temporary directory. 5 tests.

## Credits
Code and tests: glitchfox (see CONTRIBUTORS.md). Packaging and this README: the LookTwin studio. MIT License.
