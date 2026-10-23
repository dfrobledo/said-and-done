# Said and Done

**Decisions said in chat reach the project files, word for word.**

*Dicho y hecho*: las decisiones que se dicen en el chat no se pierden camino a los archivos. Funciona en inglés y en español.

A Claude Code plugin for people who make decisions in conversation with Claude: "yes, go ahead", "I accept your
proposals", "from now on…". Those decisions are the most fragile thing in a long project. They get summarized,
shortened, written down tomorrow, or not at all, and the next session works from the weaker version. A note in memory
does not fix it, because writing the note depends on the same model remembering to write it.

Said and Done moves the burden to things that do not forget:

- **A ledger** (`DECISIONS.md`): one entry per decision, with the user's exact words, the literal text of the proposal
  they accepted, and where it was applied (`PENDING` until it lives in the file that governs it).
- **A guard** (a `Stop` hook): if the user's last message carries an approval and the ledger did not change during
  the turn, the turn does not end. Claude records the decision, or says in plain sight that there was none
  (`No decision to record: <reason>`).
- **Checks** for the end of a session: entries still pending, approvals in the transcript with no entry, and which of
  your written rules are enforced by a script and which are only words.

It was built for a real production, a narrative podcast where seven decisions in three weeks did not make it intact
from the chat to the files. The only rules that never failed again were the ones a script enforced. This is that
script, for decisions.

## Install

```
/plugin marketplace add dfrobledo/said-and-done
/plugin install said-and-done@said-and-done
```

Requires Python 3 on the `PATH` (standard library only; Windows, macOS and Linux).

## Set up a project

1. Create `.claude/said-and-done.json` (every key is optional):

   ```json
   {
     "ledger": "DECISIONS.md",
     "lang": "en",
     "user": "the user",
     "user_label": "User",
     "extra_patterns": ["\\bship it\\b"]
   }
   ```

   `lang` is `en` or `es` (approval phrases, labels and messages). `user_label` is the label of the user's field in
   each entry, such as your name or initials.

2. Create the ledger with a short header. Each entry looks like this:

   ```
   ## D-0001 · 2026-10-21 · One episode at a time until done
   - **User:** «I accept your proposals»
   - **Accepted proposal:** «One episode at a time until “done”. No more parallel work.»
   - **Applied in:** `CLAUDE.md` | PENDING
   ```

3. Check that the guard works: `python scripts/ledger.py selftest` runs cases that must block and cases that must
   pass.

The skill `said-and-done:recording-decisions` tells Claude how to write entries, what to do when the guard blocks, and
what to run at the end of a session.

## Commands

| Command | What it does |
|---|---|
| `ledger.py guard` | The `Stop` hook. Reads the hook input on stdin; blocks once per turn |
| `ledger.py check` | Ledger format, paths that do not exist, entries still `PENDING` |
| `ledger.py review [transcript]` | Every approval in a session transcript with no ledger entry quoting it and no escape phrase |
| `ledger.py audit` | Your written rules (`rules_glob`) against the scripts that enforce them (`enforcers_dir`) |
| `ledger.py selftest` | Cases that must block and cases that must pass. A checker whose failing case also passes is not running |

## Where it works

The skill loads in Claude Code, Cowork and claude.ai chat. The guard is a hook, so it runs in Claude Code and Cowork;
in chat only the skill's instructions apply, with nothing to enforce them.

## What it reads and writes

Everything stays on your machine. The plugin makes no network requests, starts no other programs and installs no
packages. One readable Python file, `scripts/ledger.py`, using only the standard library:

- **Reads:** the hook input Claude Code sends on stdin; the session transcript whose path that input names (to find
  your last message); `.claude/said-and-done.json` and the ledger in your project. `review` reads the newest transcript
  of the project under `~/.claude/projects/` (or under `$CLAUDE_CONFIG_DIR/projects/` when that is set), or the files you pass. `audit` reads the rule files you list in
  `rules_glob` and the scripts under `enforcers_dir`.
- **Writes:** one line to `.claude/said-and-done-skipped.log` in your project when a blocked turn is let through the
  second time. `selftest` writes its test files in a temporary folder and deletes them. Nothing else. The ledger is written by Claude, through its normal file tools, never by the script.
- **Blocks:** a turn's end, once, by printing `{"decision": "block", "reason": …}` as the `Stop` hook protocol
  expects.

## By design

- **The guard is dumb on purpose.** No model judges whether a message "was really a decision": it matches approval
  phrases. A false positive costs one visible line; a false negative can cost a working rule.
- **It blocks once per turn.** A second ignore goes through and is logged to `.claude/said-and-done-skipped.log`,
  which the checks surface.
- **A question is not an order.** "Maybe we publish it?" is recorded as open; the outward action still needs its own
  yes.

## Limits

- An imperative that decides something without an approval word ("Remove the producer") is not seen by the guard.
  `review` and the user are the net; add your own phrases to `extra_patterns`.
- "Changed in this turn" compares the ledger's modification time with the time of the user's message.
- `review` reads Claude Code's JSONL transcripts.

## License

MIT
