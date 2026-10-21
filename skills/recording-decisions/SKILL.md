---
name: recording-decisions
description: Keeps every decision the user makes in chat from getting lost on its way to the project files. Use when the user approves, accepts, picks, rejects or sets a standing rule ("yes", "go ahead", "I accept your proposals", "from now on…", "acojo", "procede", "de ahora en adelante"), when a Stop-hook message from the approval guard blocks the turn, when closing a session or a unit of work, and when the user asks why a decision they made was not applied. Records each decision in the ledger with the user's exact words and the literal text of the proposal, tracks it until it is applied, and audits which rules are enforced by a script and which are only words.
---

# Said and Done: recording decisions

A decision said in chat is the most fragile thing in a project. It gets summarized, shortened, written down tomorrow,
or not at all, and the next session works from the weaker version. Notes in memory do not fix this, because writing the
note depends on the same model remembering to write it. This skill moves the burden to a ledger file, a hook that will
not let the turn end without it, and a script that checks both.

Everything runs through one stdlib-only script, `${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py` (`guard`, `check`, `review`, `audit`, `selftest`).

## The ledger

One markdown file at the project root (`DECISIONS.md` by default; set in `.claude/said-and-done.json`). One entry per
decision:

```
## D-0007 · 2026-10-21 · One episode at a time until done
- **User:** «Suspend the producer… And I accept your proposals»
- **Accepted proposal:** «One episode at a time until “done”. No more parallel work.»
- **Applied in:** `CLAUDE.md`, `.claude/STATE.md` | PENDING
```

(The config's `lang` picks the labels: in Spanish, `**Usuario:**`/`**Propuesta aceptada:**`/`**Aplicada en:**` and
`PENDIENTE`. `user_label` replaces `User`/`Usuario` with the name the project uses for the user.)

## When the user decides

Write the entry **in the same turn**, before anything else, then do the work.

1. **The user's exact words**, in quotes. Never a paraphrase: the paraphrase is where decisions die. Cut with `[…]`,
   never reword.
2. **The literal proposal they accepted**, copied from your own earlier message. If they said "I accept your
   proposals" to a list of five, write **five entries**, one per proposal. An approval of a bundle is not an approval of
   whatever the bundle contained that they did not read: if one item was presented as a separate question and they did
   not name it, it is still open; record it as an open entry and ask about it by name.
3. **Applied in:** `PENDING` until the decision lives in the file that governs it (instructions, rules, state, code).
   Then list those files. A decision is not applied because it is in the ledger; the ledger is the receipt.
4. A question is not an order. "Maybe we publish it?" is recorded as open, and the outward action still needs its own
   explicit yes.

## When the guard blocks the turn

The Stop hook fires after each response. If the user's last message contains an approval phrase and the ledger did not
change during the turn, it blocks once with a reason. Then either:

- record the decision(s) as above, or
- if there truly was no decision (a "yes" to "shall I continue?", an already-recorded rule), write in the answer the
  escape phrase from the config (`No decision to record: <reason>` / `Sin decisión que registrar: <motivo>`) with the
  reason. It is visible to the user on purpose: a skipped decision must be a visible choice, not a silent one.

The guard blocks only once per turn (`stop_hook_active`); a second ignore is let through and logged to
`.claude/said-and-done-skipped.log`, which `check` and the end-of-session sweep surface. It is deliberately dumb: no
model judges whether the message "was really a decision". False positives cost one line; a false negative cost us a
season's working rule.

## At the end of a session or a unit of work

Run, and report the numbers to the user:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" check     # format errors, missing paths, PENDING entries
python "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" review    # approvals in this session's transcript with no entry and no escape
python "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" audit     # rules with an enforcing script vs rules that are only words
```

- Any `UNRECORDED` from `review`: write the entry now, or tell the user why not.
- Any `PENDING`: apply it or tell the user it is still pending and why. Never close a session silently on one.
- `audit` is a compass, not a gate: a rule that keeps failing and is "only words" is a candidate for a script, the way
  a style guide becomes a linter. Propose one when a rule fails twice.

## When the user asks "what happened to the rule we agreed?"

Search the transcripts for the exact words before answering (`review` lists every approval with its date). Quote what
was said and what was written, show the gap, fix the ledger and the governing file, and say which of the two failed.
Do not answer from memory.

## Setup in a project

1. Copy or install the plugin; the Stop hook is in `hooks/hooks.json`. In a project without the plugin, register
   `python <path>/ledger.py guard` as a `Stop` command hook in `.claude/settings.json`.
2. Create `.claude/said-and-done.json`: `ledger`, `lang` (`en` or `es`), `user` (how messages name the user),
   `user_label` (the label of the user's field in each entry),
   optional `extra_patterns` (regexes), and for `audit`, `rules_glob` and `enforcers_dir`.
3. Create the ledger file with a short header and the format above.
4. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" selftest`: cases that must block and cases that must pass. If you change the
   patterns, break the guard on purpose once and check that the selftest fails.

## Limits

- The trigger is a list of phrases, so an imperative that decides something without an approval word ("Remove the
  producer") goes unseen by the guard; `review` and the user remain the net. Add the user's own phrases to
  `extra_patterns` when you notice them.
- "Changed in this turn" is the ledger's modification time against the user's message time.
- The transcript format is Claude Code's JSONL; another host needs its own reader.
