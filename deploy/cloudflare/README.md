# Cloudflare staging adapter

This is a separate Cloudflare Worker and Python Container for the GrokCell
repair probe. It does not modify or share Relay's Worker. The public surface
has two GET routes:

| Route | Result |
|---|---|
| `/healthz` | 200 only when the frozen repair contracts verify |
| `/preflight` | Contract count, arm names, variants, and paired-pilot readiness |

All other routes are unavailable. The container holds no provider credentials,
does not open GrokCell state, and has no endpoint that runs a model, generated
code, or a paid experiment. The current paired pilot remains blocked because
the fixture gives Jev no productive routing choice. This adapter is a staging
status surface, not a production repair service.

The repository root contains `wrangler.jsonc`, `package.json`, and the lockfile.
The image builds from the repository root and copies only the OSAHR and GrokCell
packages plus the frozen repair contracts. The Worker name is
`osahr-grokcell-preflight`, separate from Relay.

## Deploy and verify

Cloudflare Containers require a Workers Paid plan. The workstation used to
prepare this change lacks Docker, so use Cloudflare Workers Builds to build the
image. Connect `SyberLabs/OSAHR_Cell` in the Cloudflare dashboard, set the
project root to the repository root, the production branch to `main`, and the
deploy command to `pnpm exec wrangler deploy`. For Container projects, a
Worker-only upload does not deploy the image. Use `wrangler deploy`.

After the build reports success, request both routes at the Worker URL and
verify `/preflight` reports `paired_pilot_ready: false` and
`live_execution_enabled: false`. Verify an attempted `/live` returns 404.
Do not infer a running Container from a successful Worker upload alone.

For local code validation without Docker:

```bash
pnpm install --frozen-lockfile
pnpm exec wrangler deploy --dry-run --containers-rollout=none
cd grokcell && python -m pytest tests/test_repair_status_http.py -q
```

The dry run bundles the Worker and validates its binding. It cannot verify the
image or a live Cloudflare deployment. No provider keys or budget file should
be configured for this staging adapter.
