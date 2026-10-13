# Flect

**Agentic CI/CD that protects production.** Flect runs next to the application it guards and uses a
local, offline LLM (DeepSeek-V4-Flash on llama.cpp) as its reasoning engine. It:

1. **Stops poisonous PRs.** It runs static analysis, secret detection, dependency and sensitive-path checks, and an
   LLM intent review, then runs the tests in a no-network sandbox. It posts required statuses, blocks or closes risky
   PRs, and auto-merges clean feature PRs into `uat`.
2. **Watches logs continuously.** It detects anomalies and **blocks IPs doing DoS/DDoS** with nftables. Blocks
   have escalating TTLs, an allowlist the root helper also enforces, and a flood-mode rate limit for distributed
   attacks.
3. **Runs VAPT before prod.** Every release PR (`uat → main`) gets a read-only assessment of the **UAT
   instance only**: static scan, TLS, headers, and an anonymous-access sweep of every API route. The report is
   posted on the PR, and a human merges.
4. **Saves production when it crashes.** It detects crashes on its own (health probes, restart loops,
   repeated tracebacks). It **rolls back to the last-known-good commit first**, without the LLM. Then it asks the
   model for a fix plus a regression test, and requires the test to fail on the old code and pass on the new code
   in the sandbox. If that holds, it **auto-merges and deploys the hotfix**, watches it, and rolls back if it
   regresses.
5. **Is the pipeline.** It polls GitHub, guards, merges, deploys UAT, smoke-tests, runs VAPT, deploys prod after
   the human merge, and watches. It also checks **API keys, tokens and certificates for expiry** every hour.

The only autonomous merge into production is a verified crash hotfix. Everything else that reaches prod is
merged by a human.

For a tour of every feature, what sets it off and what it does, see [WALKTHROUGH.md](WALKTHROUGH.md).

## How it decides

```
 sources (observe)            detectors (deterministic)       policy engine (the ONLY actor)    actuators (audited)
 ───────────────────          ─────────────────────────       ──────────────────────────────    ───────────────────
 GitHub poller (ETag)  ──►    PR guard                  ──►   rules.py + modes + pause    ──►   gh / git as soczap
 log tailer            ──►    DoS / anomaly             ──►   off | observe | enforce     ──►   nft (sudo helper)
 health + systemd      ──►    crash                     ──►                               ──►   deploy / rollback
 key / cert / token    ──►    expiry                    ──►                               ──►   sandbox, notify
                                     ▲
                        LLM gateway: priority queue, ≤2 in flight, JSON-schema output only,
                        no tools; untrusted text is fenced and redacted; may RAISE risk, never clear it
```

- **The LLM proposes; deterministic code decides.** Model output is schema-validated data. It cannot call
  tools, cannot clear a deterministic block, and never triggers an action directly.
- **Observe first.** Every capability ships in `observe` mode, which records what it *would* do. Turn on one
  capability at a time with `flect mode <capability> enforce`.
- **Every action is audited** in a hash-chained log (`/api/audit/verify`).
- **Secrets never leave the process.** Values are redacted from LLM prompts, GitHub text, logs and the
  dashboard.
- **Identity.** Every commit, push, PR and comment is made as **soczap**. The git actuator refuses to push if
  the tip commit is not soczap's or carries any AI attribution trailer.

## Layout

```
flect/
  config.py            defaults → flect.toml → FLECT_* env
  db/                  SQLite (WAL) schema, audit chain
  gateway/llm.py       local model client + priority queue
  sources/             github, logs, health, keys
  detect/              dos, anomaly, crash
  analyze/             prguard, vapt, hotfix, soc/ (vendored SOC scanner)
  policy/              engine (act/modes/pause), rules, crashflow, cicd
  actuators/           git+gh, nft, deploy, sandbox, notify
  daemon.py            wiring + supervised loops + control socket
  server.py, static/   read-only dashboard (127.0.0.1:1113); static/ is built from web/
  cli.py               flect run | status | mode | unblock | pause | resume | keys
deploy/
  flect.service        systemd --user unit
  vigil-uat.service    UAT instance on 127.0.0.1:8190
  root/                one-time privileged setup (nft table, helper, sudoers, AppArmor)
web/                   dashboard source: React, Tailwind, shadcn/ui (npm run build → flect/static)
tests/                 pytest suite (fakes for the model, GitHub, nft and deployer)
```

The built dashboard is committed in `flect/static/`, so running Flect never needs Node. After changing
anything in `web/`, rebuild it; the running service picks up the new files on the next page load:

```bash
cd web && npm ci && npm run build      # writes flect/static/{index.html,app.js,app.css,assets/}
npm run dev                            # live-reload on :5173, proxying /api to the running Flect
```

## Setup (DGX Spark, user `enterprise`)

```bash
git clone https://github.com/soczap/flect.git ~/flect && cd ~/flect
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp flect.example.toml flect.toml            # all capabilities start in observe mode
.venv/bin/python -m pytest                  # full test suite
.venv/bin/flect keys                        # one-shot expiry/liveness check

mkdir -p ~/.config/systemd/user
cp deploy/flect.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now flect
flect status                                 # or open http://127.0.0.1:1113
```

### One-time steps that need a human

| Step | Why | Command |
|---|---|---|
| Rotate the GitHub token | the soczap PAT expires **2026-10-15 08:28 UTC**; with `keys` in enforce, Flect pauses GitHub writes when it expires | create a fine-grained PAT for `soczap/flect` + `soczap/Computer_Vision` (Contents, Pull requests, Commit statuses, Issues, Administration: read/write), then `gh auth login --with-token < token.txt` |
| Privileged setup | enables IP blocking and the test sandbox (Ubuntu 24.04 blocks unprivileged user namespaces) | `sudo ~/flect/deploy/root/install-root.sh` |
| Remove llama.cpp shell tools | `--tools all` lets anything that reaches :1111 run shell commands; Flect feeds the model attacker-controlled text | `pkill -x llama-server && TOOLS=none ~/deepseek/run-deepseek.sh` (~7 min reload) |
| Point prod at Computer_Vision | `~/VIGIL` still tracks `soczap/video-analytics`; trees are identical except 4 slide files | move the untracked `ppt_*`/slide files aside, then `git -C ~/VIGIL remote set-url origin https://github.com/soczap/Computer_Vision.git` |
| UAT branch + instance | feature PRs land in `uat`; VAPT runs against the UAT instance | `gh api repos/soczap/Computer_Vision/git/refs -f ref=refs/heads/uat -f sha=$(gh api repos/soczap/Computer_Vision/branches/main --jq .commit.sha)`; `git clone https://github.com/soczap/Computer_Vision.git ~/VIGIL-uat`; `mkdir -p ~/VIGIL-uat-data/{logs,certs}`; create a self-signed cert in `~/VIGIL-uat-data/certs`; `cp deploy/vigil-uat.service ~/.config/systemd/user/` |
| Branch protection | makes Flect's statuses mandatory | require `flect/pr-guard`, `flect/secrets`, `flect/sandbox-tests` on `uat` and `main` (plus `flect/vapt` on `main`) |
| Enforce | after reviewing "would_do" actions on the dashboard | `flect mode dos enforce`, `flect mode crash enforce`, … |

## Operating

```bash
flect status                 # health, modes, sandbox/nft/UAT/LLM availability
flect mode crash enforce     # off | observe | enforce, per capability (prguard dos crash cicd vapt keys)
flect unblock 203.0.113.9    # remove an IP block
flect pause "maintenance"    # stop all GitHub writes; detection and blocking continue
flect resume
```

### Overriding a needs-human verdict

`uat` and `main` are branch-protected: GitHub refuses a merge unless `flect/pr-guard`, `flect/secrets` and
`flect/sandbox-tests` are green, and that applies to admins too. When Flect marks a PR **needs-human** (for
example a dependency bump or binary files), a listed approver (`[github] approvers`, default `soczap`) comments
a line starting with:

```
/flect approve <optional reason>
```

Flect then sets its checks to green, recording who approved, and you merge. **Blocked** PRs (high-severity
findings, secrets, failing tests, prompt-injection attempts) cannot be approved this way. A new push is
reviewed from scratch.

Reports (PR guard, VAPT, incidents) are written to `data/reports/` and shown on the dashboard. Set
`[notify] github = true` to also open GitHub issues for incidents.

## Limits (honest list)

- VAPT is read-only: GET requests only, no exploit payloads, and only routes without path parameters are swept
  anonymously. "No findings" does not prove the release is secure.
- IP blocking protects this host. A volumetric DDoS that saturates the uplink needs upstream mitigation.
- Fix-forward quality depends on the local model. The safety net is the red→green regression gate,
  rollback-first, and auto-rollback after a bad hotfix, not the model being right.
- A crash caused by the environment (disk, memory, ports, unreachable services, certificates) gets a restart and a
  human. It does not get a code change.
- Without the privileged setup, the sandbox is unavailable. Then the PR guard is static-only and never
  auto-merges, and fix-forward is skipped.
