---
name: haslamq
description: Run long tests, benchmarks or batch jobs on the shared remote machine through the haslamq queue instead of running them directly, and wait for them without polling. Use whenever a command will take >1 minute, use many cores, or lots of RAM, and whenever you are waiting for queued jobs or experiments.
---
<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# haslamq job queue

Never run heavy jobs directly on the shared host; queue them. The daemon starts jobs
when CPU/RAM beyond a reserve for other users is free, at idle CPU priority.
Name each campaign with `--owner <short-label>` (haslamres experiments use `exp-<name>`); the jobs also record this
session automatically (`$CLAUDE_CODE_SESSION_ID`), and that is what makes them yours.
If this session is not on the host: `export HASLAMQ_SSH=<host>` (commands run there; paths are host paths).

```bash
haslamq submit --cpus 4 --mem 12G --timeout 30m --owner router-v3 --name t1 -- pytest -x tests/foo   # one job
haslamq submit --batch cmds.txt --cpus 2 --mem 6G --owner sweep                                       # one command per line
haslamq wait                      # Bash run_in_background: true, timeout 7200000. Returns when your jobs need you
haslamq status                    # a few lines: resources, counts, running + problems
haslamq result 42                 # error lines + log tail of one job
haslamq retry 42 [--mem 20G]      # after fixing the code (same cmd/cwd); or --owner X. Bare `haslamq retry`: only one owner's <12 h old failures
haslamq set --owner sweep --timeout 2x [--running]   # change limits of your queued (or running) jobs
haslamq cancel --owner sweep
haslamq note <session|owner> "..."   # tell another session something about its jobs (see below)
haslamq sessions                  # who owns which campaigns, how far along, who is listening
```

## Waiting: let the dispatcher message you; otherwise one background `haslamq wait`

Usually a relay session runs `haslamq dispatch`, which watches every session's jobs. Then `haslamq submit` says so, and
the dispatcher **messages you** at a campaign's first failure, its 25% mark and its end (plus urgent notes). Just
stop after submitting: don't wait, poll or schedule anything. When its message arrives, act on it and stop again.
`haslamq wait` exits 6 at once while a dispatcher runs.

Without a dispatcher, after submitting, start `haslamq wait` in the background (Bash `run_in_background: true`, `timeout: 7200000`). It
covers every job this session submitted, under any owner. It wakes you only for a campaign's first result, its first
failure, 25% of it done, and its end, and it decides how to wait:
- **5: nothing is due within 100 minutes** (queue forecast; checked again every 10 minutes while it blocks). It
  exits and prints a time. Schedule exactly ONE
  wake-up for that time (`send_later(at=...)`, message "Start `haslamq wait` in the background") and do nothing else
  until it fires. A day-long campaign costs a handful of wake-ups, not one every two hours. Failures in between are
  reported at that wake-up.
- Otherwise it blocks (no tokens) and exits with:
  - 1: the first failure in a campaign (later failures there are held until you `haslamq retry` or the next wake-up):
    fix, `haslamq retry`, start `haslamq wait` again;
  - 4: a campaign is 25% done (once: check its first results look sane), a campaign finished (analyse it), or an
    urgent note: act, then start it again;
  - 0: nothing of yours is queued or running.
  If Claude Code stops it at its 2-hour limit (a forecast was wrong), just start it again: look at nothing else.
Health warnings and notes never wake you; they are printed at the next wake-up, with each campaign's progress.

Do not poll the queue: no other `send_later`, `ScheduleWakeup`, `CronCreate` or `Monitor` loops, no `sleep`/`until`
loops, and no repeated `haslamq status`, `haslamqtop` or log tails to see how jobs are doing. Each such wake-up re-reads
your whole context; `haslamq wait` tells you when there is something to see.

## Your jobs only; notes instead of messages

- Look after your own session's jobs and experiments only: don't wait on, retry, cancel, re-prioritise, analyse
  or report on another session's. haslamq refuses the changing commands on them (`--force` only if the user asks), and
  `haslamq result` says whose they are. Reading another session's finished `REPORT.md` is fine; watching its run is not.
- To tell another session something about its jobs or code: `haslamq note <session-or-owner> "..."`. It reads the note
  the next time its `haslamq wait` returns, when it is looking at its jobs anyway. Use `--urgent` only if the problem is
  breaking its running work now.
- Send a direct message (SendMessage / send_message) only to answer a question put to you, or when you are blocked on
  something only that session can do. Put everything in one message. No status updates, FYIs, thanks or
  acknowledgements.

## Details

Code is frozen at submit time: inside a git repo the job runs a snapshot (HEAD + uncommitted + untracked, ignored files excluded) in a private worktree,
so switching branches or editing afterwards does not affect queued jobs. Needs git-ignored inputs (data, venv)? `--link haslam-work --link .venv`.
`--live` runs in the directory as-is (submit prints why whenever a job runs live). `haslamq retry` re-snapshots from the original directory, so fixes are picked up.
Default owner is `repo@branch`; failures print `repo@branch:sha`.
Jobs that need KiCad (pcbnew, kicad-cli, haslambench, haslam tests): `haslamq submit --kicad ...` sources `~/.cache/haslambench/env.sh` in the job.

Estimate `--cpus`/`--mem` honestly:
`--mem` is a job's starting memory grant. A job that needs more is not killed: a timed job gets it first (a batch job makes room); a batch job pauses at its
grant, frozen, until the queue can give it more (1 GB or 25%, more when much is free) and gets it back when it
frees memory, so
declare the typical need, not the worst case. Jobs are `--class batch` by default: packed tight, and may be paused (frozen, their memory compressed) when
memory runs short. Use `--class timed` for timing, benchmark, optimization and speed work, whose results depend on
the time it gets: never paused, CPU priority over batch jobs. (haslamres experiment runs are submitted as timed.) Time frozen does not count towards `--timeout`;
`haslamq usage` shows per owner the time active, frozen, CPU used and work lost to requeues. (Without the cgroup memory controller, the old rule applies:
RSS over 1.5x `--mem` is killed and requeued with a corrected value.)
Do not use `--retries` for deterministic test failures. Details: `tools/haslamq/README.md`.
