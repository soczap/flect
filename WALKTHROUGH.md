# Flect walkthrough

This is a tour of everything Flect does: what each feature is for, what sets it off, what it does about it,
and where you see the result. For installation and the one-time privileged steps, see the [README](README.md).

Flect is an agent that lives next to **VIGIL** (the production video-analytics service) on the DGX Spark and
keeps it safe. It watches pull requests, traffic, logs, health checks, and credentials, and acts on what it
finds: it blocks attackers, rolls back bad deploys, writes and ships verified crash fixes, runs a security
assessment before every release, and drives the whole CI/CD pipeline. Its reasoning engine is the local
DeepSeek-V4-Flash model running on llama.cpp, so nothing leaves the machine.

## Contents

1. [How Flect thinks](#1-how-flect-thinks)
2. [Modes: off, observe, enforce](#2-modes-off-observe-enforce)
3. [PR guard: stopping poisonous pull requests](#3-pr-guard-stopping-poisonous-pull-requests)
4. [Traffic shield: DoS and DDoS blocking](#4-traffic-shield-dos-and-ddos-blocking)
5. [Log anomaly detection](#5-log-anomaly-detection)
6. [Crash recovery: rollback, then fix-forward](#6-crash-recovery-rollback-then-fix-forward)
7. [CI/CD: the pipeline itself](#7-cicd-the-pipeline-itself)
8. [Release VAPT](#8-release-vapt)
9. [Keys and services](#9-keys-and-services)
10. [DeepSeek, and how Flect keeps it on a leash](#10-deepseek-and-how-flect-keeps-it-on-a-leash)
11. [Incidents, reports and GitHub issues](#11-incidents-reports-and-github-issues)
12. [The audit log](#12-the-audit-log)
13. [Safety and security model](#13-safety-and-security-model)
14. [The dashboard, page by page](#14-the-dashboard-page-by-page)
15. [The `flect` command](#15-the-flect-command)
16. [Configuration](#16-configuration)
17. [What runs where](#17-what-runs-where)
18. [Limits](#18-limits)

---

## 1. How Flect thinks

Flect has four layers, and only one of them is allowed to change anything:

```
 sources (observe)         detectors (deterministic)     policy engine (the ONLY actor)   actuators (audited)
 GitHub poller      ──►    PR guard               ──►    rules + modes + pause      ──►   gh / git as soczap
 log tailer         ──►    DoS / anomaly          ──►    off | observe | enforce    ──►   nft (firewall helper)
 health + systemd   ──►    crash                  ──►                               ──►   deploy / rollback
 keys / certs       ──►    expiry                 ──►                               ──►   sandbox, notify
                                   ▲
                      DeepSeek: explains, classifies, proposes. Never decides.
```

The rules that follow from this:

- **The model proposes; plain code decides.** DeepSeek returns JSON that must match a schema. It has no
  tools, so it cannot run commands, merge, block or deploy. It can make a verdict stricter, never looser.
- **Every action goes through one function** (`Engine.act`). It checks the capability's mode and the GitHub
  write pause, then either does the action or records what it *would* have done. It writes an audit row
  either way.
- **Production is merged by a human**, with one exception: a crash hotfix that has proved itself with a
  failing-then-passing regression test.
- **Everything Flect writes to GitHub is done as `soczap`**, with no AI attribution. The git layer refuses
  to push anything else.

## 2. Modes: off, observe, enforce

Flect has six capabilities, and each one has its own mode:

| Capability | Name on the dashboard | What enforce lets it do |
|---|---|---|
| `prguard` | PR guard | Set PR statuses, comment, label, close critical PRs, auto-merge green feature PRs into `uat` |
| `dos` | Traffic shield | Block IPs in the firewall, turn flood mode on and off |
| `crash` | Crash recovery | Roll back or restart production, push a hotfix branch, open and merge the hotfix PR, deploy it |
| `cicd` | CI/CD | Deploy UAT when `uat` moves, deploy production after a human merges into `main` |
| `vapt` | Release VAPT | Post the VAPT report and the `flect/vapt` status on release PRs |
| `keys` | Keys and services | Nothing extra today: the checks, their incidents and the automatic GitHub pause run in every mode |

The three modes:

- **off**: the capability does nothing at all.
- **observe**: it detects and reports, and logs each action as **"Would do"** instead of doing it. Every
  capability ships in observe so you can review what it would have done before trusting it.
- **enforce**: it acts.

Change a mode at runtime with `flect mode <capability> <mode>`. The change takes effect immediately and is
itself written to the audit log. Setting `dry_run = true` in `flect.toml` forces every capability to observe.

**Pausing GitHub writes.** `flect pause "reason"` stops every GitHub write (statuses, comments, merges,
issues) while detection and IP blocking carry on. `flect resume` lifts it. Flect also pauses itself when its
GitHub token expires or stops working, and resumes on its own once the token is healthy again.

## 3. PR guard: stopping poisonous pull requests

**What sets it off:** Flect polls GitHub every 30 seconds (using ETags, so unchanged polls cost nothing
against the rate limit). Every new PR, and every new push to an open PR, gets a full review. Draft PRs are
skipped until they are marked ready.

**How it classifies a PR:**

| Kind | How Flect recognises it | What happens after review |
|---|---|---|
| Feature | anything else, normally into `uat` | auto-merged into `uat` when every check is green |
| Release | `uat` → `main` | VAPT runs against UAT; a human merges |
| Hotfix | branch `flect/hotfix-*` | Flect's own crash fixes; guarded inside the crash flow |
| Back-merge | `main` → `uat` | keeps `uat` in sync after a hotfix |

**The review, step by step.** No code from the PR runs until step 5, and then only in the sandbox.

1. **Export both trees** (the merge base and the PR head) with `git archive`. No hooks, filters, LFS or
   submodules run, and unsafe paths in the archive are rejected.
2. **Static scan of both trees** with the built-in SOC scanner plus Bandit. Only findings that are *new* in
   the PR count. Rules include hard-coded secrets and key material (`SECRET-*`), `eval`/`exec`, shell
   injection, unsafe pickle and YAML loading, SQL built from strings, debug mode, privileged container
   config, wildcard IAM, and the JavaScript equivalents.
3. **Diff checks:**
   - touching sensitive paths: CI workflows, deploy and service files, Dockerfiles, `Makefile` and
     `scripts/`, authentication and security code, dependency manifests, `vigil/config.py`
   - adding or changing dependencies in `requirements*.txt`
   - binary files
   - very large changes (over 200 files or 5 MiB of diff)
4. **DeepSeek intent review.** The model gets the findings plus the PR title, body and diff (fenced as
   untrusted and redacted). It returns a risk level, a plain summary of what the PR does, cited finding IDs,
   files of concern, and whether the PR text tries to give instructions to an automated reviewer.
5. **Sandbox tests.** If nothing so far blocks the PR, VIGIL's test suite runs on the PR head in the sandbox:
   no network, no home directory, and capped memory, CPU, processes and time.

**Verdicts:**

| Verdict | When | What Flect does |
|---|---|---|
| **Pass** | no new high or critical findings, nothing sensitive, model not alarmed, tests passed | statuses green; feature PRs into `uat` are merged |
| **Needs a human** | sensitive paths, dependency changes, binaries, huge diff, model rates it high, or tests could not run | `flect/pr-guard` fails, label `flect:needs-human` |
| **Blocked** | new high or critical findings, any new secret, failing tests, or a prompt-injection attempt | `flect/pr-guard` fails, label `flect:blocked`; **critical** risk PRs are also closed |

Flect posts three commit statuses on every PR head: `flect/pr-guard`, `flect/secrets` and
`flect/sandbox-tests`. It also comments with the verdict, the reasons, a findings table, the model's summary
and the test result, and saves the same text as a PR guard report.

**Overriding "needs a human".** An approver listed in `[github] approvers` (default `soczap`) comments a line
starting with `/flect approve`, optionally followed by a reason. Flect turns its checks green, records who
approved, and comments to confirm. It never merges on its own after an approval. Blocked PRs cannot be
approved this way, and a new push is reviewed from scratch.

**If the model is down,** the review continues on deterministic checks alone. **If the sandbox is
unavailable,** tests are not run and the PR is never auto-merged.

## 4. Traffic shield: DoS and DDoS blocking

**What it watches:** VIGIL's access log, line by line. No model is involved in blocking.

**The rules** (thresholds from `[dos]` in `flect.toml`):

| Rule | Fires when | Default |
|---|---|---|
| `DOS-RATE-001` | one IP sustains a high request rate | over 20 req/s for 10 seconds |
| `DOS-AUTH-001` | one IP fails to log in too often | over 50 failed logins (401/429 on `/api/auth/login`) per minute |
| `DOS-SCAN-001` | one IP probes paths that don't exist | over 60 distinct paths answered 400/403/404/405 per minute |
| `DOS-FLOOD-001` | total traffic jumps far above normal | over 5× the learned baseline and over 50 req/s |

**Flood mode.** Flect learns a baseline request rate (a slow moving average that an attack cannot drag
upwards). When total traffic floods past it:
- every per-IP threshold drops to a quarter, so the heaviest sources in a distributed attack get caught
- the firewall adds a per-source limit on new connections to VIGIL's ports
- both are lifted when traffic returns to normal

**Blocking.** A flagged IP is dropped by nftables on VIGIL's production and UAT ports (8090 and 8190). Block
length grows with repeat offences in 24 hours: **15 minutes, then 1 hour, then 24 hours**. Blocks expire on
their own, are re-applied after a reboot if they are still due, and can be lifted with
`flect unblock <ip>`.

**The allowlist always wins.** Loopback, the LAN, the Tailscale address and range, and a few reserved ranges
can never be blocked. This is enforced twice: by Flect, and again by the root-owned `flect-nft` helper, so a
bug in one cannot lock you out.

Each block opens a "DoS" incident with the rule, reason and evidence, and DeepSeek writes a short
plain-language explanation for the operator.

## 5. Log anomaly detection

Alongside DoS detection, Flect counts errors and server errors per minute against a learned baseline. It
reports:

- **error spikes** and **5xx spikes**: a minute with at least 20 events and more than 4× the baseline
- **new error signatures**: an exception type and location never seen before

Spikes are high severity and open an incident. New signatures are recorded as signals. As with traffic, a
spike barely moves the baseline, so an ongoing attack cannot make itself look normal.

**Live events only.** Log lines older than two minutes are skipped and counted, never acted on. This stops
Flect from reacting to old tracebacks replayed after an unclean reboot.

## 6. Crash recovery: rollback, then fix-forward

### Detecting a crash

| Severity | Meaning | Triggered by |
|---|---|---|
| **S1** | production is down | 3 failed health checks in a row (every 5 seconds), the systemd unit not running, or 2 restarts within 2 minutes |
| **S2** | a code path keeps crashing | the same exception at the same place 5 times within 10 minutes |

Flect is careful not to fight people or itself:
- a unit stopped on purpose (`inactive`) is left alone
- after a restart (new process ID) there is a 90-second grace period before failed health checks count
- crash signals are ignored while Flect itself is deploying or restarting production

### Classifying it

- **Code**: the traceback runs through VIGIL's own code and shows no environmental cause.
- **Environment**: disk full, out of memory, port in use, permission denied, a dependency service
  unreachable, a missing module, a locked database, or a certificate problem. No code change can fix these.
- **Unknown**: no traceback available.

### Step A: save production, without the model

When production is down (S1):

1. If production is not on the **last-known-good** commit, roll back to it. A commit becomes last-known-good
   after 10 healthy minutes with no open crash. The rollback must pass health checks for 60 seconds.
2. Otherwise, restart the service; it must then pass health checks for 30 seconds.
3. At most **3 automatic production deploys per hour**. Past that, Flect stops and asks for a human rather
   than loop.

The incident resolves on its own once health checks pass again. Environmental crashes get a restart if
production is down, then the incident is marked **needs a human**. An S2 error burst leaves production
running and goes straight to step B.

### Step B: fix forward, with proof

For code crashes, meaning the traceback runs through VIGIL's own code:

1. DeepSeek gets the traceback and the relevant source, and proposes the smallest fix as a patch, plus a
   regression test at `tests/test_flect_<name>.py`.
2. The patch must stay within limits: at most 5 files and 200 changed lines, and it may not touch
   `deploy/`, `.github/`, `Makefile`, `vigil/security.py` or `vigil/api/auth.py`.
3. In the sandbox, the regression test **must fail on the deployed code and pass with the patch**, and the
   full test suite must pass.
4. If a check fails, the model sees why and tries again, up to 3 attempts. The same crash is not retried
   for 6 hours.

When a fix proves itself, Flect:
- pushes `flect/hotfix-<incident>` as `soczap`
- opens a `[flect] Hotfix` PR into `main` and runs the PR guard on it
- merges it automatically (the only autonomous merge into production) and deploys it
- rolls back to last-known-good if the deploy fails its 60-second health check
- resolves the incident and opens a back-merge PR into `uat`

If no fix proves itself, the incident records why, and production stays on the rolled-back commit.

## 7. CI/CD: the pipeline itself

```
feature PR ──► PR guard ──► auto-merge into uat ──► deploy UAT
                                                        │
release PR (uat → main) ──► PR guard ──► VAPT on UAT ──► a human merges ──► deploy prod ──► watch
                                                                                │
                                                       failed health check ──► roll back to last-known-good
```

- **When `uat` moves,** Flect deploys it to the UAT instance (`~/VIGIL-uat`, port 8190).
- **When `main` moves** (a human merged a release), Flect deploys it to production and verifies health.
  A failed deploy rolls back to last-known-good automatically.
- **UAT on demand.** UAT shares memory with the 104 GB model, so it starts only for a deploy or a scan and
  stops afterwards.
- **Changes made outside Flect** (someone ran `git checkout` in `~/VIGIL`) are noticed and recorded as
  "Changed outside Flect".

**Deploy safety rules:**
- production is moved with `git checkout --detach <sha>` only; no `reset --hard` or `clean`, because the
  checkout also holds data, `.env` and certificates
- Flect refuses to deploy over local modifications to tracked files
- dependencies are reinstalled only when `requirements.txt` actually changed between the two commits
- the restarted service must stay healthy for 60 seconds

## 8. Release VAPT

Every release PR (`uat` → `main`) that the guard doesn't block gets a vulnerability assessment of the **UAT
instance only**. Flect first deploys the release commit to UAT (when CI/CD is enforcing), then scans it. The
scan is read-only: GET requests, no exploit payloads.

**Scope guard.** The target must be exactly the configured UAT address on loopback, and never a production
port. Anything else is refused before a single request is sent.

**Checks:**

| Check | What it looks at |
|---|---|
| `VA-STATIC` | full static scan of the release tree (SOC scanner plus Bandit). Findings in `scripts/`, `tests/`, `tools/`, `docs/` and `benchmarks/` are lowered, since that code is not served |
| `VA-HTTP` | security headers and cookie attributes on the UI |
| `VA-TLS` | protocol version, certificate validity window, self-signed certificates |
| `VA-AUTHZ` | every GET route in the OpenAPI spec without path parameters must refuse anonymous access, unless it is on the public list (health, login, docs) |
| `DEP-OSV` | optional: known-vulnerable dependencies via OSV. Off by default because it sends package names and versions to `api.osv.dev` |

Requests come from `127.0.0.2` rather than `127.0.0.1`, because apps often exempt exactly `127.0.0.1` from
authentication, which would hide what a remote attacker sees.

**The result.** DeepSeek writes an executive summary using only the findings above, picks up to 10 to
prioritise, and recommends ship, ship with follow-ups, or don't ship. The release **passes** when nothing
is high or critical. Flect posts the report on the PR, sets `flect/vapt`, saves the report, and leaves the
merge to a human.

## 9. Keys and services

Every hour, Flect checks:

| What | Kind | How |
|---|---|---|
| The `soczap` GitHub token | GitHub token | `gh` login works; expiry from GitHub's token-expiry header |
| `~/VIGIL/certs/server.crt` | TLS certificate | expiry date in the file |
| VIGIL's live HTTPS endpoint (`127.0.0.1:8090`) | TLS certificate | expiry of the certificate actually served |
| JWTs in `~/VIGIL/.env` | JWT | the `exp` claim of every JWT-shaped value |
| llama-server (DeepSeek), Ollama | Service | answers on its health URL |
| FRS backend (`VIGIL_FRS_URL`) | Service | answers, when it is on this machine |
| Anything in `[keys] extra` | Service | answers on the given URL |

**Alert levels:** healthy, then **expires in a month** (certificates only), **in a week**, **in 3 days**,
**in a day**, **expired**, or **failing** (a liveness check failed). Each new level opens an incident with a
short runbook (how to rotate the token, renew the certificate, and so on), and the incident closes on its own
when the item is healthy again.

**No false alarms at boot.** A single failed check is ignored; anything failing is re-checked after two
minutes, and only a second failure counts.

**Token protection.** If the GitHub token expires or stops working, Flect pauses all GitHub writes
automatically, and resumes once it works again. Secret values are read only inside this module and never
leave it.

## 10. DeepSeek, and how Flect keeps it on a leash

Flect uses the local model for four jobs, served in this priority order:

1. **Crash fixes** (up to 15 minutes per call)
2. **PR reviews** (up to 20 minutes)
3. **VAPT summaries** (up to 30 minutes)
4. **Incident narratives** (up to 5 minutes)

Guard rails:
- loopback only, with no proxies and no redirects
- at most 2 requests in flight, since the model's memory is shared
- every answer must match a JSON schema and is validated again on arrival
- no tool definitions are ever sent, so the model can only return data
- logs, diffs, PR text and tracebacks are fenced as **untrusted**, and the system prompt tells the model to
  treat any instructions inside them as evidence, never as commands
- secrets are redacted from everything before it is sent
- when the model is down, every feature falls back to its deterministic part

Each call is recorded (task, priority, queue and run times, tokens, outcome) and summarised on the
dashboard.

## 11. Incidents, reports and GitHub issues

**Incidents** are opened by DoS blocks, crashes, log anomalies and key alerts. Duplicates are merged. Each
one moves through: **open**, **mitigating**, **mitigated**, **needs a human**, **resolved**. A "production
down" incident resolves on its own when health checks pass again, a crash that gets a hotfix when the fix is
deployed, and a key incident when the item recovers.

**Reports** are Markdown files in `data/reports/`, one per PR guard review, VAPT run and incident. The
dashboard lists them and renders them in full.

**GitHub issues.** With `[notify] github = true`, each incident also opens an issue on the target repo,
labelled `flect` plus its kind (`crash`, `dos`, `expiry`, `anomaly`). When Flect resolves the incident, it
comments on the issue and closes it. Every message is redacted, and nothing is posted while GitHub writes are
paused.

## 12. The audit log

Every action, done or "would do", is a row with time, decision, target, parameters, mode, outcome and the
incident it belongs to. Each row stores the hash of the previous row, forming a chain:
editing or deleting any entry breaks it. The dashboard's Audit log page checks the chain and shows
**"Chain intact, no tampering"** or **"Chain broken"**.

## 13. Safety and security model

- **Sandbox.** Untrusted code (PR heads, model-written patches) runs under `bwrap` with every namespace
  unshared, so there is no network at all, not even to local services. `/usr` and `/etc` are read-only, the
  home directory (with the GitHub token and SSH keys) is not mounted, and `/tmp` is a fresh tmpfs. A systemd
  scope caps it at 2 GB of memory, 2 CPUs, 256 processes and 10 minutes. Without the sandbox, Flect never runs
  untrusted code at all.
- **One privileged entry point.** Firewall changes go through `/usr/local/sbin/flect-nft`, a root-owned
  helper that sudo allows for the Flect user only. It accepts five commands, validates every argument, never
  uses a shell, and refuses to block allowlisted ranges whatever it is asked.
- **Identity guard.** Before any push, the git layer checks that the tip commit's author is `soczap` and that
  the message has no AI attribution trailer. Otherwise it refuses.
- **Secrets never leave the process.** Private keys, GitHub tokens, AWS keys, JWTs, bearer tokens,
  password-style settings and credentials in URLs are redacted from model prompts, GitHub text, logs and the
  dashboard.
- **The dashboard can't change anything.** It only has read endpoints, listens on `127.0.0.1` only, and a test
  fails if a write endpoint is ever added. Changes go through the `flect` command, over a Unix socket only
  your user can open.
- **Resilience.** Each of Flect's loops (logs, traffic, health, keys, GitHub, events, housekeeping,
  dashboard) is supervised: if one crashes it restarts with back-off instead of taking Flect down.

## 14. The dashboard, page by page

Open `http://127.0.0.1:1113` on the Spark (or tunnel the port to your laptop). It refreshes every 5 seconds,
works offline, follows your system's light or dark theme (the sun and moon button switches it), and fits a
phone screen. Press **Ctrl K** (⌘K on a Mac) to jump to any page, open incident or recent report.

**Overview** answers "is production safe right now?"
- A one-line verdict: *Production is protected*, *Production is up. One thing needs you*, or *Production is
  not responding*, with a status light and the reason.
- **VIGIL's heartbeat:** every health check of the last hour drawn like a patient monitor, with failed
  checks as red bars and a strip showing availability minute by minute. Next to it: response time now, the
  hourly average, availability and uptime.
- **Guards:** the six capabilities with their mode, key number and whether what they depend on (sandbox,
  firewall, DeepSeek, UAT, GitHub) is up. Click one to go to its page.
- **Needs you:** open incidents, plus recently resolved ones.
- **What Flect did:** the latest actions as a timeline.
- **DeepSeek:** online or offline, queue, calls, average call time and tokens in the last 24 hours.
- **Traffic this hour:** requests per second against the baseline, with flood periods shaded.

**Incidents.** Open, resolved or all incidents, with severity shown as a coloured edge. Click one to open a
drawer with the facts, DeepSeek's read (summary, likely cause, follow-ups), the traceback and evidence, and
every action Flect took. Each incident has its own link, such as `#/incidents/11`.

**Traffic and blocks.** Current request rate against the baseline, flood mode, IPs blocked now, the hour's
traffic chart, the busiest sources of the last minute, the allowlist, and every block with its rule, reason,
length and status (blocked with time left, would block, expired, unblocked). Shows the unblock command with a
copy button.

**Keys and services.** Expiring credentials and certificates with a time-left bar, and every token and
dependent service with its last check and status.

**Pull requests.** How a change reaches production, and every reviewed PR with its verdict, risk, test
result, links to its guard and VAPT reports, and links to GitHub.

**Deployments.** What runs in production, the rollback target, deploys in the last 24 hours, and the full
history as a timeline: what triggered each deploy, its result and the commit it replaced.

**Reports.** Every VAPT, PR guard and incident report, filterable by kind. Click one to read it in full, with
severities highlighted.

**Audit log.** Every action, filterable by done, would do and failed, with the tamper check result.

**Settings.** Each guard's mode, the commands to change Flect (with copy buttons), and the environment:
what is protected, production and UAT addresses, branches, sandbox, firewall, DeepSeek and GitHub status,
log lines read, and Flect's version and uptime.

## 15. The `flect` command

| Command | What it does |
|---|---|
| `flect status` | health, modes, availability of sandbox, firewall, UAT and DeepSeek, traffic snapshot |
| `flect mode <capability> <off\|observe\|enforce>` | change one capability's mode now (capabilities: `prguard dos crash cicd vapt keys`) |
| `flect pause "<reason>"` | stop all GitHub writes; detection and blocking continue |
| `flect resume` | allow GitHub writes again |
| `flect unblock <ip>` | lift a firewall block |
| `flect keys` | run the key, certificate and service checks once and print them (works without the daemon) |
| `flect run` | run the daemon in the foreground (systemd normally does this) |

## 16. Configuration

Settings come from three places, each overriding the one before: built-in defaults, `~/flect/flect.toml`,
then `FLECT_*` environment variables (`FLECT_MODE_DOS=enforce`, `FLECT_DRY_RUN=1`, `FLECT_DATA_DIR=...`).
`flect.example.toml` is a starting point.

| Section | Main settings |
|---|---|
| `[general]` | `data_dir`, `dry_run` |
| `[modes]` | one mode per capability |
| `[github]` | `repo`, `feature_base` (`uat`), `prod_branch` (`main`), `approvers`, poll interval |
| `[notify]` | `github`: also open GitHub issues for incidents |
| `[dos]` | `allowlist`, `per_ip_rps`, `per_ip_sustain_s`, `failed_logins_per_min`, `failed_paths_per_min`, flood factor and floor, block lengths |
| `[crash]` | health interval and failure count, restart-loop and error-burst windows, last-known-good minutes, hotfix size limits and forbidden paths, fix attempts |
| `[keys]` | check interval, warning days, certificate warning days, `extra` services to probe |
| `[vapt]` | `osv`: opt in to the online dependency check |
| `[target]` | VIGIL's directories, systemd units, URLs, log files, TLS certificates, and whether UAT runs on demand |
| `[llm]` | model URL, requests in flight, per-task timeouts, output and prompt limits |
| `[sandbox]` | memory, CPU, process and time limits |
| `[dashboard]` | host and port |

## 17. What runs where

| Thing | Where |
|---|---|
| Flect | `systemctl --user` unit `flect.service`, code in `~/flect`, data in `~/flect/data` |
| Dashboard | `http://127.0.0.1:1113` |
| Control socket | `~/flect/data/flect.sock` (owner-only) |
| VIGIL production | `~/VIGIL`, `vigil.service`, `https://127.0.0.1:8090` |
| VIGIL UAT | `~/VIGIL-uat`, `vigil-uat.service`, `https://127.0.0.1:8190`, started on demand |
| DeepSeek | llama-server at `http://127.0.0.1:1111/v1` |
| Firewall | nftables table `inet flect`, loaded at boot by `flect-nft.service` |
| Reports | `~/flect/data/reports/` |
| Dashboard source | `~/flect/web` (built into `flect/static`, see the README) |

## 18. Limits

- VAPT is read-only: GET requests, no exploit payloads, and only routes without path parameters are tested
  anonymously. "No findings" does not prove a release is secure.
- IP blocking protects this host. A flood that saturates the network link needs upstream protection.
- Fix-forward is only as good as the local model. The safety net is rollback first, the red-then-green
  regression test, and rolling back a hotfix that fails its health check, not the model being right.
- Crashes with an environmental cause get a restart and a human, never a code change.
- Without the privileged setup there is no sandbox, so the PR guard is static-only and never auto-merges,
  and fix-forward is skipped.
