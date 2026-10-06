# sn-ragas-platform — Claude Code context

## Deploy target facts

- Repository is public (required for branch protection on free personal GitHub account).
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
