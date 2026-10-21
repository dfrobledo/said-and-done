# Privacy policy

Said and Done collects no data.

- It makes no network requests and sends nothing anywhere: not to the author, not to a server, not to a third party.
- It runs one local Python script, `scripts/ledger.py`, on your machine. That script reads your project's ledger and
  configuration, and the Claude Code session transcript whose path Claude Code passes to the hook, only to find your
  last message. It writes one local log file, `.claude/said-and-done-skipped.log`, in your project.
- No analytics, no telemetry, no accounts.

Everything the plugin reads and writes is listed in the README, under "What it reads and writes".

Questions: open an issue at https://github.com/dfrobledo/said-and-done/issues
