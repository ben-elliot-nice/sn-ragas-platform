# CI/CD and zip-to-git handover — design

## Purpose

Changes to this service currently arrive from Shannon as a zip drop (extracted
to a local scratch directory), with an accompanying natural-language
description of "what changed" that must be treated as untrusted and verified
by diffing against the repo. Each change is then manually reviewed, copied
in, committed, built, pushed to DOCR, and deployed to DigitalOcean App
Platform by hand.

This is the last change accepted via that zip process. Going forward, Shannon
contributes via git (branch + PR). This document designs the CI/CD pipeline
that gates and automates that future git-based flow, and the procedural
how-to (landing in this repo's `CLAUDE.md`) for folding in a zip drop if one
ever arrives again despite the new process being in place.

Out of scope: teaching generic git or CI/CD concepts — the how-to links to
reference material for those rather than explaining them inline.

## Current state (as of this session)

- GitHub repo: `ben-elliot-nice/sn-ragas-platform` (private), branch `main`,
  no branch protection yet.
- DigitalOcean: Container Registry `sn-ragas-platform` (region `syd1`), App
  Platform app `sn-ragas-platform` (id `aade8c38-7593-4c7a-abd9-94e351d4e34d`,
  region `syd`), custom domain `ragas.nice-agentic.com` via a Cloudflare
  CNAME (DNS-only, not proxied), scale-to-zero via `inactivity_sleep.after_seconds:
  900` on the `web` service.
- App secrets (`API_KEY`, `OPENAI_API_KEY`) are stored as `SECRET`-type env
  vars directly on the DO app spec — not in this repo, not in CI.
- Deploys so far have been entirely manual: `docker buildx build --platform
  linux/amd64 ... --push` followed by `doctl apps create-deployment --wait`.
- Tests: 32 pytest tests, all using fakes — no live OpenAI key required to
  run them (confirmed working this session via a `uv`-managed venv with
  `pytest` + `pytest-asyncio` added, since neither is in `requirements.txt`,
  which lists runtime deps only).

## Design

### Workflow triggers

Single workflow file, `.github/workflows/ci.yml`, two triggers:

- `pull_request` targeting `main` → runs the `test` job only.
- `push` to `main` (i.e. a PR just merged) → runs `test`, then on success
  `build` → `push` → `deploy`.

### Jobs

**`test`**
- Runs on `ubuntu-latest`.
- Installs `uv`, creates a venv, installs `requirements.txt` plus `pytest`
  and `pytest-asyncio` (dev-only test deps; intentionally not added to
  `requirements.txt`, which describes runtime deps for the Docker image).
- Runs `pytest -q`.
- No secrets required.

**`build`** (push-to-main only, `needs: test`)
- Runs on `ubuntu-latest` — natively `linux/amd64`, so no cross-platform
  `buildx --platform` flag is needed in CI (this sidesteps the arm64-vs-amd64
  mismatch that broke the first manual deploy this session, which happened
  because the image was built on Apple Silicon).
- Builds the image using `docker/build-push-action` with
  `cache-from`/`cache-to: type=gha` to avoid re-resolving the full
  `ragas`/`langchain`/`numpy`/`pandas` dependency tree on every merge.

**`push`** (part of the same build-push-action step, or a discrete step)
- Authenticates to DOCR via `digitalocean/action-doctl` +
  `doctl registry login`, using the `DIGITALOCEAN_ACCESS_TOKEN` secret.
- Pushes two tags: `registry.digitalocean.com/sn-ragas-platform/sn-ragas-platform:latest`
  and `...:${{ github.sha }}`. The `:latest` tag is what the DO app spec
  references; the sha tag exists purely as a traceability/manual-rollback
  pointer (re-tag an old sha as `:latest` and redeploy) — no automated
  rollback is being built now.

**`deploy`** (`needs: push`)
- `doctl apps create-deployment aade8c38-7593-4c7a-abd9-94e351d4e34d --wait`.
- No app spec update, no secrets beyond the one DO token — the app spec's
  image reference (`:latest`) doesn't change, so this is a pull-and-restart,
  not a spec mutation. This is why `API_KEY`/`OPENAI_API_KEY` never need to
  exist in GitHub Actions.

### Secrets

Exactly one new secret, `DIGITALOCEAN_ACCESS_TOKEN`, stored as a GitHub
Actions repo secret. This should be a **new, dedicated DO API token**, not a
copy of the personal token already used locally via `doctl` — so it can be
scoped/rotated/revoked independently of personal access.

### Branch protection

`main` requires the `test` status check (from the `pull_request` trigger) to
pass before a PR can merge. This is the actual enforcement mechanism: once
live, Shannon's future PRs cannot merge with failing tests, and merging is
what triggers the real build/push/deploy.

### Error handling

- `test` fails on a PR → merge blocked by branch protection; nothing else
  runs.
- `test` fails on a push to main (e.g. an admin force-merge bypassing
  protection) → `build`/`push`/`deploy` don't run (`needs: test`), so a
  broken main is never auto-deployed.
- `build`/`push` succeeds but `deploy` fails → the new image sits in DOCR
  tagged `:latest`, but DO does not cut traffic to an unverified deployment;
  the previous deployment remains active. Visible as a failed Actions run,
  not a silent production break.

### CLAUDE.md how-to (procedural, not educational)

Added to this repo's `CLAUDE.md` (new file), scoped strictly to the
zip-intake procedure — generic git/CI/CD concepts are linked to reference
docs, not explained inline:

1. Confirm the incoming change is still arriving as a zip (expected to stop
   after this handover — if it's a PR instead, this procedure doesn't apply,
   just review the PR normally).
2. Diff every file in the drop against current `main` — never trust an
   accompanying description of "what changed" as ground truth for *what
   actually changed*; verify by diffing.
3. Classify each diff hunk:
   - A genuine upstream change → merge it.
   - A reversion of something this repo added independently (e.g. the
     `Dockerfile`, `.dockerignore`, the `.gitignore` fix that un-ignored
     `data/golden_set.embeddings.json`) → do not apply; these aren't
     tracked upstream and shouldn't be clobbered by a drop that doesn't know
     about them.
4. Compose the merge-ready result on a branch, commit, push, open a PR.
5. Let CI run; once the `test` check is green, merge.
6. Merging to `main` auto-deploys. Verify via `/health` and one authenticated
   `/evaluate` smoke test against the live custom domain
   (`https://ragas.nice-agentic.com`).

## Testing

- Prove the `test` job first on a throwaway PR (e.g. a no-op whitespace
  change) to confirm the workflow triggers and branch protection blocks
  merge on failure.
- Prove the full `build`/`push`/`deploy` path by merging a real change to
  main and confirming the live app updates (checked via `/health` and a
  smoke-test `/evaluate` call, same as every manual deploy this session).
- The upcoming held-back change (mentioned by the user, not yet shared) is
  the intended end-to-end proof run: process it through this exact
  procedure once CI exists, confirm it deploys cleanly, *then* hand over to
  Shannon.

## Open items / explicitly deferred

- No linter is being added — none exists in the repo today, and adding one
  wasn't requested; YAGNI.
- No automated rollback — the sha-tagged images make manual rollback
  possible, but building a one-click rollback mechanism is future work, not
  part of this change.
- `LOG_DESTINATION` still points at a container-local file, unrelated to
  this change — flagged in earlier sessions as a pre-existing gap, not
  addressed here.
