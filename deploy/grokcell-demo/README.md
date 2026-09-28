# GrokCell static report package

This folder prepares one Cloudflare Pages upload: the allowlisted `public/`
directory contains only `index.html` and `_headers`. The report is a sanitized
offline fixture recording. It does not contain run state, credentials, source
code, test files, or provider response payloads. Pages hosts this static report;
it does not run the Python engine.

## Rebuild and inspect locally

From `grokcell/`, after installing the full checkout in an isolated environment:

```text
python -m grokcell.execution demo --out <new-private-demo-directory> --static-export <new-static-export-directory>
```

Both paths must be new. The demo command performs offline fixture workflows and
fresh-process replay, then writes a separate allowlisted export. It refuses to
export a live run. The private demo directory contains state and JSON evidence;
never upload it. The static-export destination must not already exist. Before
sharing the static report, inspect the page and verify the upload allowlist:

```powershell
Get-ChildItem -File <new-static-export-directory> | Select-Object -ExpandProperty Name
```

Expected files are exactly `index.html` and `_headers`. To update the checked-in
package, copy only those reviewed files into `deploy/grokcell-demo/public/`.
Review the HTML itself; it is the complete report. The page makes no network
requests. Its workflow controls are native buttons and work with keyboard focus
and activation.

## Cloudflare preparation and access checks

No account, project, visibility, hostname, or Cloudflare spend grant is attached
to this package. Do not create a Pages project or upload it until a separate
grant names those items. Cloudflare Pages Direct Upload accepts a folder of
prebuilt assets; dashboard drag-and-drop accepts a folder or ZIP. Wrangler
deploys a directory, not the demo-kit ZIP. Direct Upload projects cannot later
be converted to Git integration. See the [Direct Upload guide](https://developers.cloudflare.com/pages/get-started/direct-upload/).

After the grant, an authorized operator can use the reviewed static-export
directory with Wrangler:

```text
npx wrangler pages deploy <static-export-directory> --project-name <granted-project> --branch review
```

Use the production branch only when the grant explicitly includes production:

```text
npx wrangler pages deploy <static-export-directory> --project-name <granted-project> --branch main
```

These commands are prepared examples, not executed commands. The branch name
`review` creates a preview deployment; it does not make that preview private.

After an authorized deployment, first confirm the exact uploaded files and
deployment identity. Test both workflows, keyboard operation, a narrow mobile
viewport, browser console/network activity, and the visible recorded-fixture
label. No calls to Jev or Hugging Face should occur.

If the approved audience is restricted, configure Cloudflare Access before
sharing the deployment and verify logged-out denial plus approved-user access
for every hostname: random deployment URL, `pages.dev`, branch alias, and any
custom domain. Pages preview protection alone does not protect the production
`pages.dev` hostname or custom domain. `noindex` is not access control. See
[preview access](https://developers.cloudflare.com/pages/configuration/preview-deployments/)
and [Pages Access coverage](https://developers.cloudflare.com/pages/platform/known-issues/).

For a custom subdomain, associate it in Pages first and follow the DNS target
Cloudflare gives for that project. A custom domain must be attached to Pages;
adding a CNAME alone can fail. See [custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/).

## Rollback

Record the approved export hash and successful production deployment ID. If a
production upload needs reversal, select a previously successful production
deployment in Pages > Deployments and use its rollback action. Preview
deployments are not production rollback targets. For a preview-only deployment,
deploy the previous approved static folder. A website rollback does not change
any GrokCell run journal. See [Pages rollbacks](https://developers.cloudflare.com/pages/configuration/rollbacks/).

## Readiness

Package preparation is local only. Cloudflare preview, production, custom
domain, access policy, and rollback behavior have not been exercised against an
account. The handoff must separately provide the account/project, allowed
visibility and audience, hostname, and budget before any Cloudflare mutation.
