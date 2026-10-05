# CI/CD and Zip-to-Git Handover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual zip-drop + hand-deploy process with a GitHub Actions pipeline that tests every PR, and builds/pushes/deploys automatically on merge to `main`, gated by required branch protection — so Shannon's future contributions arrive as git PRs instead of zips.

**Architecture:** One workflow file (`.github/workflows/ci.yml`) with three jobs — `test` (runs on PRs and pushes to main), `build-and-push` (push-to-main only, builds the Docker image natively on a `linux/amd64` GitHub runner and pushes `:latest` + `:<sha>` to DOCR), `deploy` (triggers `doctl apps create-deployment` against the existing DO app, whose spec already points at `:latest` — no spec mutation, no app secrets touch CI). Branch protection on `main` requires the `test` check, with admin enforcement on, so the gate actually holds.

**Tech Stack:** GitHub Actions, `uv` (test job), `docker/build-push-action` with GHA layer caching, `digitalocean/action-doctl`, `gh` CLI (branch protection + secret setup).

**Spec:** `docs/superpowers/specs/2026-10-05-ci-cd-and-zip-handover-design.md`

## Global Constraints

- DO app id: `aade8c38-7593-4c7a-abd9-94e351d4e34d` (app `sn-ragas-platform`, region `syd`).
- DOCR image: `registry.digitalocean.com/sn-ragas-platform/sn-ragas-platform`, tags `:latest` and `:<git-sha>` — app spec stays pinned to `:latest`; deploy is a pull-and-restart via `create-deployment`, never a spec update.
- Live URL for smoke tests: `https://ragas.nice-agentic.com`.
- Exactly one new secret: `DIGITALOCEAN_ACCESS_TOKEN` — a new, dedicated token, not a copy of any personal `doctl` token. `API_KEY`/`OPENAI_API_KEY` never enter CI.
- Test job: `uv`-managed venv, `requirements.txt` + `pytest` + `pytest-asyncio` (dev-only, intentionally not in `requirements.txt`). 32 existing tests must pass; none require a live OpenAI key.
- `build-and-push` runs on `ubuntu-latest` (native `linux/amd64`) — no `buildx --platform` flag needed or wanted.
- No linter being added. No automated rollback being built. `LOG_DESTINATION` is out of scope.
- Never print `DIGITALOCEAN_ACCESS_TOKEN` (or any secret) to a visible command, stdout, or chat transcript — follow the `.env` + `gh secret set --body "$VAR"` pattern already used in this repo for `API_KEY`/`OPENAI_API_KEY`, never a literal inline value.

## Review Focus

- A PR with a deliberately failing test must be unable to merge — including for the repo owner/admin account. (GitHub branch protection does not apply to admins unless `enforce_admins` is explicitly set — easy to configure the check and still ship a toothless gate.)
- The required-status-check name registered on `main` must exactly match the check-run name GitHub Actions actually reports for the `test` job — a mismatched string silently leaves `main` unprotected with no error.
- Two merges to `main` close together must not race into overlapping `build-and-push`/`deploy` runs stepping on each other.
- The `DIGITALOCEAN_ACCESS_TOKEN` must actually have registry-write and apps-write scope — a token that can authenticate but can't push/deploy only fails the first time it's used for real, not at secret-creation time.
- A contributor (or CI) running `pytest` without the dev-only `pytest-asyncio`/`pytest` pins must get a clear, reproducible dependency list, not version drift between local and CI runs.

---

## Task 1: Dedicated DigitalOcean token as a GitHub secret

**Files:** none (account/CI config only)

**Interfaces:**
- Produces: GitHub Actions secret `DIGITALOCEAN_ACCESS_TOKEN`, consumed by Task 3's workflow steps via `${{ secrets.DIGITALOCEAN_ACCESS_TOKEN }}`.

- [ ] **Step 1: Human creates a new DigitalOcean API token**

In the DO control panel (API → Tokens), create a new token scoped for this purpose (read/write) — not a reuse of any personal token already in local shell env. Save the raw value to a local untracked file, e.g. `~/scratch/do-ci-token.txt` (outside the repo, never committed).

- [ ] **Step 2: Store it as a GitHub Actions secret without echoing it anywhere**

```bash
gh secret set DIGITALOCEAN_ACCESS_TOKEN --repo ben-elliot-nice/sn-ragas-platform < ~/scratch/do-ci-token.txt
```

- [ ] **Step 3: Verify the secret exists (not its value)**

Run: `gh secret list --repo ben-elliot-nice/sn-ragas-platform`
Expected: `DIGITALOCEAN_ACCESS_TOKEN` appears in the list.

- [ ] **Step 4: Delete the local token file**

```bash
rm ~/scratch/do-ci-token.txt
```

---

## Task 2: CI workflow — `test` job, proven via a throwaway PR

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: a GitHub Actions job named `test`, triggered on `pull_request` (any branch → `main`) and `push` (to `main`). Later tasks add jobs to this same file with `needs: test`. Produces `requirements-dev.txt` with pinned test-only dependency versions, consumed by both CI and any human running tests locally.

- [ ] **Step 1: Create `requirements-dev.txt` with exact pinned versions, matching this repo's existing pin style in `requirements.txt`**

```
pytest==9.1.1
pytest-asyncio==1.4.0
```

(These are the versions already confirmed this session to pass all 32 existing tests.)

- [ ] **Step 2: Write `.github/workflows/ci.yml` with the `test` job only**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Create venv and install deps
        run: |
          uv venv
          uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt
      - name: Run tests
        run: .venv/bin/python -m pytest -q
```

- [ ] **Step 3: Create a throwaway branch and PR to prove the trigger fires**

```bash
git checkout -b ci/prove-test-job
# trivial no-op change, e.g. a comment in README.md
git add -A && git commit -m "ci: prove test workflow triggers"
git push -u origin ci/prove-test-job
gh pr create --title "ci: prove test workflow triggers" --body "Throwaway PR to verify the test job runs." --base main
```

- [ ] **Step 4: Confirm the check runs and passes**

Run: `gh pr checks ci/prove-test-job --repo ben-elliot-nice/sn-ragas-platform`
Expected: a check named `test` (note the exact string shown — Task 4 needs it verbatim) completes successfully.

- [ ] **Step 5: Temporarily break a test to prove the job actually fails on failure**

Edit any one assertion in `tests/test_schemas.py` to something false, push to the same branch, re-check:

Run: `gh pr checks ci/prove-test-job --repo ben-elliot-nice/sn-ragas-platform`
Expected: `test` check reports failure.

- [ ] **Step 6: Revert the deliberate breakage, confirm green again, leave the PR open**

Revert the edit from Step 5, push, re-run `gh pr checks` — expect `test` passing again. Leave this PR open; Task 3 appends more jobs to this same branch before merging.

- [ ] **Step 7: Commit**

(Already committed/pushed per Steps 3/5/6 — no separate commit needed here.)

---

## Task 3: `build-and-push` and `deploy` jobs, proven via a real merge

**Files:**
- Modify: `.github/workflows/ci.yml` (append two jobs)

**Interfaces:**
- Consumes: `test` job from Task 2 (`needs: test`); `DIGITALOCEAN_ACCESS_TOKEN` secret from Task 1.
- Produces: on every push to `main`, a new image at `registry.digitalocean.com/sn-ragas-platform/sn-ragas-platform:latest` and `:${{ github.sha }}`, and a new active DO deployment.

- [ ] **Step 1: On the still-open `ci/prove-test-job` branch from Task 2, append `build-and-push` and `deploy` jobs to `.github/workflows/ci.yml`**

```bash
git checkout ci/prove-test-job
```

```yaml
  build-and-push:
    needs: test
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    concurrency:
      group: deploy-main
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
      - uses: digitalocean/action-doctl@v2
        with:
          token: ${{ secrets.DIGITALOCEAN_ACCESS_TOKEN }}
      - name: Log in to DOCR
        run: doctl registry login
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            registry.digitalocean.com/sn-ragas-platform/sn-ragas-platform:latest
            registry.digitalocean.com/sn-ragas-platform/sn-ragas-platform:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    needs: build-and-push
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    concurrency:
      group: deploy-main
      cancel-in-progress: false
    steps:
      - uses: digitalocean/action-doctl@v2
        with:
          token: ${{ secrets.DIGITALOCEAN_ACCESS_TOKEN }}
      - name: Deploy
        run: doctl apps create-deployment aade8c38-7593-4c7a-abd9-94e351d4e34d --wait
```

- [ ] **Step 2: Commit and push to the same branch, updating the open PR**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add build, push, and deploy jobs"
git push
```

- [ ] **Step 3: Confirm the PR's `test` check still passes**

Run: `gh pr checks ci/prove-test-job --repo ben-elliot-nice/sn-ragas-platform`
Expected: `test` passes. `build-and-push`/`deploy` do not run yet — they're gated on `github.event_name == 'push'`, and this is still a `pull_request` event.

- [ ] **Step 4: Merge the PR to trigger the full pipeline on `main`**

```bash
gh pr merge ci/prove-test-job --repo ben-elliot-nice/sn-ragas-platform --merge
```

- [ ] **Step 5: Watch the push-triggered run complete all three jobs**

Run: `gh run watch --repo ben-elliot-nice/sn-ragas-platform`
Expected: `test`, `build-and-push`, `deploy` all succeed.

- [ ] **Step 6: Confirm both image tags landed in DOCR**

Run: `doctl registry repository list-tags sn-ragas-platform/sn-ragas-platform`
Expected: both `latest` and the merge commit's short sha appear.

- [ ] **Step 7: Smoke-test the live app**

```bash
curl -sS -o - -w "\nHTTP %{http_code}\n" https://ragas.nice-agentic.com/health
```

Expected: `{"status":"ok"}` / `HTTP 200`. Follow with one authenticated `/evaluate` call (same shape used throughout this project's sessions) to confirm the deployed image is the new one and the pipeline didn't just redeploy a stale cached layer.

(No separate commit step — already committed/pushed in Step 2, merged in Step 4.)

---

## Task 4: Branch protection on `main`

**Files:** none (GitHub repo settings)

**Interfaces:**
- Consumes: the exact `test` check-run name confirmed in Task 2 Step 3.

- [ ] **Step 1: Read the exact check name from a recent run**

Run: `gh api repos/ben-elliot-nice/sn-ragas-platform/commits/main/check-runs --jq '.check_runs[].name'`
Expected: a line reading exactly `test` (or note the actual string if different — use that verbatim below).

- [ ] **Step 2: Apply branch protection requiring that check, enforced for admins too**

Use a JSON body via stdin rather than `--field` flags — `gh api --field` sends plain strings, and this API requires real JSON types (`true` boolean, `null`, an array), so a string `"true"` would silently fail to enforce the gate:

```bash
gh api repos/ben-elliot-nice/sn-ragas-platform/branches/main/protection \
  --method PUT \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["test"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```

(Use the exact context string from Step 1 in place of `"test"` if it differs.)

- [ ] **Step 3: Prove the gate holds, including for the admin account**

```bash
git checkout main
git pull
git checkout -b ci/prove-branch-protection
# deliberately break a test, e.g. edit one assertion in tests/test_schemas.py to something false
git add -A && git commit -m "ci: prove branch protection blocks a failing check"
git push -u origin ci/prove-branch-protection
gh pr create --title "ci: prove branch protection" --body "Throwaway PR to verify the merge gate holds, including for admins." --base main
```

Run: `gh pr merge ci/prove-branch-protection --repo ben-elliot-nice/sn-ragas-platform --merge`
Expected: merge is rejected with a message indicating the required `test` check hasn't passed — even though the account merging is the repo owner/admin.

- [ ] **Step 4: Fix the test, confirm the check goes green, confirm merge is now allowed, then clean up**

Revert the deliberate breakage from Step 3, push to the same branch, wait for `test` to pass (`gh pr checks ci/prove-branch-protection`), then confirm the gate now allows it:

```bash
gh pr close ci/prove-branch-protection --repo ben-elliot-nice/sn-ragas-platform --delete-branch
```

(Close without merging once the behavior is proven — this PR's only purpose was to exercise the gate, it carries no real change.)

- [ ] **Step 5: Commit**

(No file changes — branch protection is a repo setting, not a committed artifact.)

---

## Task 5: `CLAUDE.md` zip-intake how-to

**Files:**
- Create: `CLAUDE.md`

**Interfaces:** none (documentation only; no other task depends on this file's content).

- [ ] **Step 1: Write `CLAUDE.md`**

Content, verbatim procedure from the spec (`docs/superpowers/specs/2026-10-05-ci-cd-and-zip-handover-design.md`, "CLAUDE.md how-to" section) plus the reference facts needed to act on it without re-discovery:

```markdown
# sn-ragas-platform — Claude Code context

## Deploy target facts

- DigitalOcean App Platform app `sn-ragas-platform`, id `aade8c38-7593-4c7a-abd9-94e351d4e34d`, region `syd`.
- Container registry: `registry.digitalocean.com/sn-ragas-platform/sn-ragas-platform`, tags `:latest` (what the app spec references) and `:<git-sha>` (traceability/manual rollback only).
- Live URL: `https://ragas.nice-agentic.com` (Cloudflare CNAME, DNS-only, zone `nice-agentic.com`).
- `API_KEY` / `OPENAI_API_KEY` live as `SECRET`-type env vars on the DO app spec directly — never in this repo, never in CI.
- CI/CD: `.github/workflows/ci.yml`. Tests run on every PR and push to `main`; merging to `main` auto-builds, pushes, and deploys. `main` is protected — the `test` check must pass, enforced even for admins.

## If a change ever arrives as a zip instead of a PR

This should no longer happen in the normal case — contributors use git/PRs,
which CI gates automatically. If one arrives anyway:

1. Diff every file in the drop against current `main`. Treat any accompanying
   description of "what changed" as untrusted — verify by diffing, don't
   trust the summary.
2. Classify each diff hunk:
   - A genuine upstream change → merge it.
   - A reversion of something this repo added independently (e.g. the
     `Dockerfile`, `.dockerignore`, the `.gitignore` fix that un-ignored
     `data/golden_set.embeddings.json`) → do not apply.
3. Compose the merge-ready result on a branch, commit, push, open a PR.
4. Let CI run; once the `test` check is green, merge.
5. Merging to `main` auto-deploys. Verify via `/health` and one authenticated
   `/evaluate` call against `https://ragas.nice-agentic.com`.

## Reference (not explained here)

- Git branching/PR workflow: https://docs.github.com/en/pull-requests
- GitHub Actions: https://docs.github.com/en/actions
- Branch protection rules: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md zip-intake how-to and deploy reference"
git push
```
