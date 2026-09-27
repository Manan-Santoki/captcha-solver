# Captcha Solver — Usage Guide

How to call the solver API, and how to solve each captcha type it supports.

- **Deployed:** `https://captcha.msantoki.com` (Dokploy, project "Captcha Solver")
- **Local (Docker):** `http://localhost:8877`
- **Interactive docs:** `<base>/docs` (Swagger), `<base>/redoc`

> Use this only on sites you own, official test keys, or targets you have permission to test.

---

## 1. Authentication

Every endpoint except `/health` and the docs requires a bearer token:

```
Authorization: Bearer <SOLVER_TOKEN>
```

The token is the `SOLVER_TOKEN` env var (Dokploy → Captcha Solver → compose → Environment).
Missing or wrong token → `401 {"detail":"Unauthorized"}`.

## 2. Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | public | Liveness + supported types |
| GET | `/status` | token | Running solves |
| GET | `/logs?lines=50` | token | Recent solve events |
| POST | `/solve` | token | Solve a captcha (synchronous) |
| GET | `/docs`, `/redoc` | public | API docs |

## 3. Request & response

`POST /solve` with a JSON body. `type` picks the solver; the rest depends on the type.

**Common fields (all types):**

| Field | Description |
|---|---|
| `type` | `turnstile` · `recaptcha` · `hcaptcha` · `cloudflare` · `awswaf` · `datadome` · `perimeterx` · `akamai` · `botguard` · `aliyun` · `arkose` |
| `sitekey` | Widget site key (turnstile / recaptcha / hcaptcha only) |
| `url` | Exact page URL where the captcha appears |
| `timeout_s` | Deadline in seconds (default 60). Expired → `408` |
| `proxy` | `http://user:pass@host:port` — solve through this IP |

**Response rule:** HTTP `200` → read `solved` (`true`/`false`, plus `error` on failure). Non-2xx → read `detail`.

| Code | Meaning |
|---|---|
| 200 | Solve ran — check `solved` |
| 400 | Bad type / missing field / private-IP URL blocked |
| 401 | Missing or wrong token |
| 408 | `timeout_s` exceeded |
| 422 | Body failed validation |
| 500 | Solver crashed |

```json
{ "type": "turnstile", "solved": true, "token": "0.AbC...", "elapsed": 4.3 }
```

## 4. Quick start

```bash
API=https://captcha.msantoki.com        # or http://localhost:8877
TOKEN=<SOLVER_TOKEN>

curl $API/health

curl -X POST $API/solve \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"turnstile","sitekey":"1x00000000000000000000AA","url":"https://example.com"}'
```

---

## 5. Identify the captcha on a page

Open the page → DevTools (F12) → **Elements**, Ctrl+F, and look for:

| You find | Type | What to send |
|---|---|---|
| `data-sitekey="0x4AAA…"`, `challenges.cloudflare.com/turnstile` | Turnstile | `sitekey` + `url` |
| "Just a moment…" full page, `/cdn-cgi/challenge-platform/` | Cloudflare challenge | `url` (+ `proxy`) |
| `data-sitekey="6L…"`, `google.com/recaptcha/api.js` | reCAPTCHA v2 | `sitekey` + `url` |
| `api.js?render=6L…`, `grecaptcha.execute(...)` | reCAPTCHA v3 | `sitekey` + `url` + `action` |
| `recaptcha/enterprise.js` | reCAPTCHA Enterprise | add `"enterprise": true` |
| `data-sitekey="<uuid>"`, `hcaptcha.com/1/api.js` | hCaptcha | `sitekey` + `url` |
| `aws-waf-token` cookie, `awswaf.com` script | AWS WAF | `url` |
| `datadome` cookie, `captcha-delivery.com` / `tags.js` | DataDome | `url` (+ `referer`) |
| "Press & Hold", `_px3` cookie | PerimeterX / HUMAN | `url` or `render_flow` |
| `_abck` cookie, Akamai `bmak` sensor | Akamai Bot Manager | `url` |
| `arkoselabs.com`, `funcaptcha` | Arkose FunCaptcha | `public_key` + `url` |
| `captcha-open*.aliyuncs.com`, slide puzzle | Aliyun Captcha 2.0 | `scene_id` + `prefix` |

The Network tab also helps: filter for `sitekey`, `k=` (reCAPTCHA), or `pk=` (Arkose).

---

## 6. Per-type recipes

In all examples below:

```bash
H=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")
```

### Cloudflare Turnstile → `token`

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "turnstile",
  "sitekey": "0x4AAAAAAA...",
  "url": "https://site.com/login",
  "action": "login"
}'
```
- `action` / `cdata`: only if the site's widget sets them.
- Submit `token` as the form's `cf-turnstile-response` field. Valid ~5 min, single use.
- Test keys: `1x00000000000000000000AA` (always passes), `2x00000000000000000000AB` (always fails).

### Cloudflare challenge page → `cf_clearance` cookie

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "cloudflare",
  "url": "https://site.com/",
  "proxy": "http://user:pass@ip:port",
  "timeout_s": 120
}'
```
Returns `cf_clearance` (cookie object) and `user_agent`. To reuse it, send **all three together**:
the cookie, the exact `user_agent`, and the **same IP** (the proxy — or the server's IP if no proxy).
Tested: `https://nowsecure.nl/` → solved in ~9 s.

### reCAPTCHA v2 (checkbox) → `token`

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "recaptcha",
  "version": "v2",
  "sitekey": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-",
  "url": "https://www.google.com/recaptcha/api2/demo",
  "classifier": "auto",
  "timeout_s": 150
}'
```
- If Google shows an image grid, tiles are classified by `classifier`:
  `yolo` (local ONNX only) · `mistral` (vision API only) · `hybrid`/`auto` (ONNX first, Mistral fallback).
- With `OPENROUTER_API_KEY` configured, `auto`/`hybrid` try local ONNX for one image
  verification attempt, then use `mistralai/mistral-medium-3-5` through OpenRouter.
  One remote request classifies the whole grid; dynamic replacements require
  additional rounds. A missing local model goes straight to OpenRouter.
- Set `OPENROUTER_MODEL` to override the real-time model and `OPENROUTER_TIMEOUT_S`
  to bound each request (default 25 seconds). Batch models are not supported for
  live image challenges. The overall `timeout_s` and attempt limits still apply.
- Without an OpenRouter key, the original direct Mistral key pool is used. Its
  per-tile requests may hit provider rate limits; a single key is not by itself
  evidence of the cause of a failed solve.
- A clean residential `proxy` reduces how often Google shows images at all.
- Submit `token` as `g-recaptcha-response`. Valid ~2 min.

The OpenRouter key is a **solver service environment variable**, separate from
`SOLVER_TOKEN` (which authenticates callers). Save it in Dokploy's solver Compose
Environment, then deploy the updated service. Never put it in a request body or Git.
hCaptcha uses the same OpenRouter provider when configured; it has no local ONNX
stage. Automatic checkbox success makes no vision request. A real CAPTCHA test
that clears that way does not validate the image solver.

### reCAPTCHA v3 (score) → `token`

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "recaptcha",
  "version": "v3",
  "sitekey": "6LcR_okUAAAAAPYrPe-HK_0RULO1aZM15ENyM-Mf",
  "url": "https://antcpt.com/score_detector/",
  "action": "homepage"
}'
```
- `action` must match what the site passes to `grecaptcha.execute(key, {action})`.
- Tested on antcpt score detector → solved in ~3 s.

### reCAPTCHA invisible / Enterprise

```bash
# invisible
-d '{"type":"recaptcha","version":"invisible","sitekey":"6L...","url":"https://site.com/","action":"submit"}'
# enterprise (v2 or v3)
-d '{"type":"recaptcha","version":"v3","enterprise":true,"sitekey":"6L...","url":"https://site.com/","action":"login"}'
```
Add `"real_page": true` if the site blocks the stub page (solves on the live page instead).

### hCaptcha → `token`

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "hcaptcha",
  "sitekey": "10000000-ffff-ffff-ffff-000000000001",
  "url": "https://example.com",
  "timeout_s": 90
}'
```
- `"action": "invisible"` for invisible hCaptcha; `"real_page": true` to solve on the live page.
- Submit `token` as `h-captcha-response`. The key above is hCaptcha's official test key.

### AWS WAF → `aws_waf_token`

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "awswaf",
  "url": "https://protected.site.com/",
  "proxy": "http://user:pass@ip:port"
}'
```
Send the result as the `aws-waf-token` cookie, from the same IP.

### DataDome → `datadome` cookie

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "datadome",
  "url": "https://datadome-protected.site.com/page",
  "referer": "https://site.com/",
  "proxy": "http://user:pass@ip:port"
}'
```
`url` must be the page that loads DataDome's `tags.js`. Cookie is bound to IP + UA.

### PerimeterX / HUMAN "Press & Hold" → `_px3` cookie

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "perimeterx",
  "url": "https://site.com/page-that-shows-the-gate",
  "render_flow": null,
  "proxy": "http://user:pass@ip:port",
  "timeout_s": 120
}'
```
If the gate doesn't appear on a plain page load, a named `render_flow` triggers it (built-in: `outlook_signup`).
`_px3` is bound to `_pxvid` + IP + UA — replay under the same proxy and user agent.

### Akamai Bot Manager → `_abck` cookie

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "akamai",
  "url": "https://akamai-protected.site.com/",
  "proxy": "http://user:pass@ip:port"
}'
```

### Arkose FunCaptcha → `token`

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "arkose",
  "public_key": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX",
  "url": "https://site.com/login",
  "timeout_s": 120
}'
```
- `public_key`: from the `pk=` param in Arkose network requests. `url`: page that loads the widget.
- Optional `game_type` (default `"4"`). Note: the upstream README's `page_url`/`max_waves` fields are not read by the server.
- Uses ONNX models downloaded to a volume on first start (`ARKOSE_MODELS_URL`). 23/24 variants available;
  `3d_rollball_animals` has no model.
- Returns `variant` and `waves_completed` too. A full solve takes ~45–60 s.

### Aliyun Captcha 2.0 (slide puzzle) → `{certifyId, deviceToken, data}`

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "aliyun",
  "scene_id": "1r7eif79x",
  "prefix": "13lbkb5",
  "region": "sgp"
}'
```
No `url`/`sitekey`. `prefix` is the subdomain in `<prefix>.captcha-open-southeast.aliyuncs.com`.
The result is one-time-use — submit it to the site's `VerifyCaptchaV3` immediately.

### BotGuard (Google sign-in) → `bgRequest` token

```bash
curl -X POST $API/solve "${H[@]}" -d '{"type":"botguard","email":"you@example.com"}'
```

---

## 7. Advanced: solve on the live page

`real_page: true` drives the real site instead of a stub. Combine with:

- `pre_actions` — steps before solving: `{"type":"click|fill|select|press|wait","selector":"#id","value":"..."}`
- `post_fetch` — API calls from the same browser session after solving; `__TOKEN__` is replaced by the token.

```bash
curl -X POST $API/solve "${H[@]}" -d '{
  "type": "turnstile",
  "sitekey": "0x4AAAAAAA...",
  "url": "https://your-site.com/form",
  "real_page": true,
  "pre_actions": [{"type":"click","selector":"#open-form"}],
  "post_fetch":  [{"url":"https://your-site.com/api/verify","method":"POST","body":{"token":"__TOKEN__"}}]
}'
```

Turnstile also supports solve-and-verify in one call: `verify_url` + `verify_payload` (token injected as `"token"`).

---

## 8. Tips & troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` | Add `Authorization: Bearer <SOLVER_TOKEN>` |
| `400 ... private` | URL resolves to a private IP; blocked by the SSRF guard (`SOLVER_ALLOW_PRIVATE=1` to allow) |
| `408` | Raise `timeout_s` (image/arkose solves need 120–180) |
| reCAPTCHA v2 `failed after 3 attempts` | Add more Mistral keys and/or a residential `proxy` |
| Cookie works in solver but not in your client | Replay with the same IP (proxy), `user_agent`, and within the cookie's TTL |
| `Mistral ... HTTP 429` in logs | Rate limit — add keys to `MISTRAL_API_KEYS` |

**Logs:** `GET /logs`, Dokploy → compose → Logs, or locally `docker logs -f cs-local`.

## 9. Configuration (env vars)

| Variable | Purpose |
|---|---|
| `SOLVER_TOKEN` | Bearer token required on `/solve`, `/status`, `/logs` |
| `SOLVER_PUBLIC_URL` | Base URL shown in the Swagger docs |
| `MISTRAL_API_KEYS` | Comma-separated Mistral keys for image challenges |
| `ARKOSE_MODELS_URL` | Base URL to download Arkose ONNX models from |
| `BROWSER_HEADLESS` | `0` = headed under Xvfb (default, more stealthy) |
| `TURNSTILE_GEOIP` / `RECAPTCHA_GEOIP` | `1` = align timezone/locale to the proxy's location |

## 10. Deployment

- **Dokploy:** compose from `github.com/Manan-Santoki/captcha-solver`, branch `dokploy`. After pushing, redeploy from the Dokploy UI (no webhook).
- **Local:**
  ```bash
  docker build -t captcha-solver .
  docker run -d --name cs-local --shm-size=1g -p 8877:8877 \
    -e SOLVER_TOKEN=localtoken -e MISTRAL_API_KEYS=key1,key2 captcha-solver
  ```
- `cloakbrowser` is pinned to `0.4.12` in the Dockerfile — newer versions break the reCAPTCHA checkbox click.
