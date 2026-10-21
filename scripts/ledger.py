#!/usr/bin/env python3
"""Said and Done: decisions said in chat do not get lost on the way to the files.

One script, standard library only (Windows, macOS, Linux):

  guard     Stop hook. If the user's last message carries an approval ("yes", "go ahead",
            "acojo", "procede"...) and the ledger did not change during this turn, it blocks
            the end of the turn and tells the model to record the decision (or to say, in
            its answer, that there was none, with the escape phrase).
  check     Validates the ledger format and lists entries still marked PENDING.
  review    Walks every user message of a session transcript and lists approvals with no
            ledger entry quoting them and no escape phrase in the reply (end-of-session sweep).
  audit     Counts which written rules have a script that enforces them and which are only words.
  selftest  Runs the guard and the checker against cases that must pass and cases that must
            fail. A checker whose failing case also passes is not running.

Configuration: <project>/.claude/said-and-done.json (all keys optional)
  {"ledger": "DECISIONS.md", "lang": "en", "user": "the user", "user_label": "User",
   "extra_patterns": ["\\bship it\\b"], "rules_glob": [], "enforcers_dir": ["tools"]}
"""
import glob
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

PATTERNS = {
    'en': [
        r'^\s*(yes|yep|yeah|ok|okay|sure)\b', r'\bapprove[sd]?\b', r'\bgo ahead\b', r'\bproceed\b',
        r"\blet'?s go with\b", r"\bi'?ll take\b", r'\bsounds good\b', r'\bdo it\b', r'\bagreed\b',
        r'\bfrom now on\b', r'\bnever again\b', r"\bdon'?t ever\b", r'\balways\b', r'\bremember that\b',
        r'\bi (choose|pick|prefer)\b', r'\baccept(ed)? (your|the|all)\b',
    ],
    'es': [
        r'^\s*s[ií]\b', r'\bacoj[oa]\b', r'\baprueb[oa]\b', r'\baprobad[oa]s?\b', r'\bprocede\b',
        r'\bproceda\b', r'\badelante\b', r'\bdale\b', r'\b(nos )?vamos con\b', r'\bme quedo con\b',
        r'\bde acuerdo\b', r'\bhazlo\b', r'\bhag[aá]moslo\b', r'\bde ahora en adelante\b',
        r'\ba partir de ahora\b', r'\bnunca m[aá]s\b', r'\bno vuelvas a\b', r'\brecuerda que\b',
        r'\bme gusta (la|el) [A-Z]\b', r'\belijo\b', r'\bqueda(n)? (as[ií]|aprobad)', r'\bsiempre\b',
    ],
}
ESCAPE = {'en': 'No decision to record:', 'es': 'Sin decisión que registrar:'}
PENDING = {'en': 'PENDING', 'es': 'PENDIENTE'}
USER_LABEL = {'en': 'User', 'es': 'Usuario'}
FIELDS = {
    'en': ('**{label}:**', '**Accepted proposal:**', '**Applied in:**'),
    'es': ('**{label}:**', '**Propuesta aceptada:**', '**Aplicada en:**'),
}
MSG = {
    'en': ('Approval guard: the last message from {user} contains {hits} and {ledger} did not change in this '
           'turn. Record each decision now (one entry per accepted proposal, with {user}\'s exact words and '
           'the literal text of the proposal; "Applied in: PENDING" until it is in the right file). If there '
           'was no decision, write "{escape} <reason>" in your answer.'),
    'es': ('Guardia de decisiones: el último mensaje de {user} trae {hits} y {ledger} no cambió en este turno. '
           'Registra cada decisión ya (una entrada por propuesta aceptada, con la frase textual de {user} y el '
           'texto literal de la propuesta; «Aplicada en: PENDIENTE» hasta que esté en su archivo). Si no hubo '
           'decisión, escribe «{escape} <motivo>» en tu respuesta.'),
}
SKIP_PREFIXES = ('<', 'Caveat:', 'This session is being continued', 'Base directory for this skill')


def load_config(root):
    cfg = {'ledger': 'DECISIONS.md', 'lang': 'en', 'user': 'the user', 'extra_patterns': [],
           'rules_glob': [], 'enforcers_dir': []}
    path = os.path.join(root, '.claude', 'said-and-done.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            cfg.update(json.load(f))
    if cfg['lang'] not in PATTERNS:
        cfg['lang'] = 'en'
    cfg['ledger_path'] = os.path.join(root, cfg['ledger'])
    return cfg


def read_entries(transcript):
    out = []
    with open(transcript, encoding='utf-8') as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def text_of(entry):
    c = entry.get('message', {}).get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        if any(isinstance(x, dict) and x.get('type') == 'tool_result' for x in c):
            return None
        return '\n'.join(x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text')
    return None


def is_prompt(entry):
    if entry.get('type') != 'user' or entry.get('isMeta') or entry.get('isCompactSummary'):
        return False
    t = text_of(entry)
    return bool(t and t.strip()) and not t.lstrip().startswith(SKIP_PREFIXES)


def ts(entry):
    s = entry.get('timestamp')
    if not s:
        return None
    return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def turns(entries):
    """[(prompt_entry, assistant_text_after_it)] in order."""
    res = []
    for e in entries:
        if is_prompt(e):
            res.append([e, []])
        elif res and e.get('type') == 'assistant':
            t = text_of(e)
            if t:
                res[-1][1].append(t)
    return [(p, '\n'.join(a)) for p, a in res]


def approvals(text, cfg):
    pats = PATTERNS[cfg['lang']] + list(cfg.get('extra_patterns', []))
    hits = []
    for p in pats:
        m = re.search(p, text, re.I | re.M)
        if m:
            hits.append(m.group(0).strip())
    return hits


def log_skip(cfg, line):
    path = os.path.join(os.path.dirname(cfg['ledger_path']), '.claude', 'said-and-done-skipped.log')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(datetime.now(timezone.utc).isoformat(timespec='seconds') + '\t' + line + '\n')


def guard_decision(hook, cfg):
    """Returns (block: bool, reason: str)."""
    tp = hook.get('transcript_path')
    if not tp or not os.path.exists(tp):
        return False, 'no transcript'
    tl = turns(read_entries(tp))
    if not tl:
        return False, 'no prompt'
    prompt, reply = tl[-1]
    hits = approvals(text_of(prompt), cfg)
    if not hits:
        return False, 'no approval'
    t0 = ts(prompt)
    if os.path.exists(cfg['ledger_path']) and t0 and os.path.getmtime(cfg['ledger_path']) >= t0:
        return False, 'ledger changed'
    if ESCAPE[cfg['lang']] in reply:
        log_skip(cfg, 'escape\t' + text_of(prompt)[:200].replace('\n', ' '))
        return False, 'escape'
    if hook.get('stop_hook_active'):
        log_skip(cfg, 'ignored-after-block\t' + text_of(prompt)[:200].replace('\n', ' '))
        return False, 'already blocked once'
    shown = ', '.join('«%s»' % h if cfg['lang'] == 'es' else '"%s"' % h for h in hits[:4])
    return True, MSG[cfg['lang']].format(user=cfg['user'], hits=shown, ledger=cfg['ledger'],
                                         escape=ESCAPE[cfg['lang']])


def cmd_guard(root):
    try:
        hook = json.loads(sys.stdin.read() or '{}')
    except ValueError:
        return 0
    cfg = load_config(hook.get('cwd') or root)
    block, reason = guard_decision(hook, cfg)
    if block:
        sys.stdout.write(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
    return 0


def is_pending(applied, cfg):
    """PENDING alone, or after the files already done: `a.md` | PENDING."""
    word = PENDING[cfg['lang']]
    return applied.startswith(word) or bool(re.search(r'\|\s*' + word + r'\s*$', applied))


def parse_ledger(path, cfg):
    """Returns (entries, errors). entry = dict(id, title, user, proposal, applied)."""
    if not os.path.exists(path):
        return [], ['no ledger at %s' % path]
    text = open(path, encoding='utf-8').read()
    body = re.split(r'^## ', text, flags=re.M)[1:]
    entries, errors = [], []
    f_user, f_prop, f_app = FIELDS[cfg['lang']]
    f_user = f_user.format(label=cfg.get('user_label') or USER_LABEL[cfg['lang']])
    seen = set()
    for chunk in body:
        head = chunk.split('\n', 1)[0]
        m = re.match(r'(D-\d{4}) · (\d{4}-\d{2}-\d{2}) · (.+)', head)
        if not m:
            errors.append('bad heading: ' + head[:80])
            continue
        did = m.group(1)
        if did in seen:
            errors.append('%s: duplicate id' % did)
        seen.add(did)
        e = {'id': did, 'title': m.group(3)}
        for key, label in (('user', f_user), ('proposal', f_prop), ('applied', f_app)):
            mm = re.search(r'^- ' + re.escape(label) + r'\s*(.+)$', chunk, re.M)
            if not mm or not mm.group(1).strip():
                errors.append('%s: missing %s' % (did, label))
            e[key] = mm.group(1).strip() if mm else ''
        entries.append(e)
    return entries, errors


def cmd_check(root):
    cfg = load_config(root)
    entries, errors = parse_ledger(cfg['ledger_path'], cfg)
    pend = [e for e in entries if is_pending(e['applied'], cfg)]
    missing = []
    for e in entries:
        for p in re.findall(r'`([^`]+)`', e['applied']):
            if ('/' in p or '.' in p) and not os.path.exists(os.path.join(root, p.split(' ')[0])):
                missing.append('%s: %s does not exist' % (e['id'], p))
    print('%d entries, %d pending, %d format errors, %d missing paths' % (len(entries), len(pend), len(errors), len(missing)))
    for x in errors + missing:
        print('  ERROR ' + x)
    for e in pend:
        print('  %s %s · %s' % (PENDING[cfg['lang']], e['id'], e['title']))
    return 1 if errors or missing else 0


def norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[«»"“”‘’\'.,;:!?¿¡()\[\]…*_-]', ' ', s.lower())).strip()


def quote_fragments(user_field):
    frags = []
    for q in re.findall(r'«([^»]+)»', user_field) or [user_field]:
        for part in re.split(r'\[…\]|\.\.\.|…', q):
            n = norm(part)
            if len(n) >= 12:
                frags.append(n)
    return frags


def project_transcripts(root):
    slug = re.sub(r'[^A-Za-z0-9]', '-', os.path.abspath(root))
    base = os.path.join(os.path.expanduser('~'), '.claude', 'projects', slug)
    return sorted(glob.glob(os.path.join(base, '*.jsonl')), key=os.path.getmtime)


def cmd_review(root, args):
    cfg = load_config(root)
    paths = args or project_transcripts(root)[-1:]
    if not paths:
        print('no transcript found')
        return 1
    entries, _ = parse_ledger(cfg['ledger_path'], cfg)
    frags = [(e['id'], f) for e in entries for f in quote_fragments(e['user'])]
    uncovered = 0
    for path in paths:
        for prompt, reply in turns(read_entries(path)):
            t = text_of(prompt)
            hits = approvals(t, cfg)
            if not hits:
                continue
            nt = norm(t)
            ids = sorted({i for i, f in frags if f in nt})
            if ids:
                status = 'ok ' + ','.join(ids)
            elif ESCAPE[cfg['lang']] in reply:
                status = 'ok (escape)'
            else:
                status = 'UNRECORDED'
                uncovered += 1
            print('%-16s %s  %s' % (status, prompt.get('timestamp', '')[:16], t[:110].replace('\n', ' ')))
    print('%d approvals without an entry' % uncovered)
    return 1 if uncovered else 0


def cmd_audit(root):
    cfg = load_config(root)
    files = []
    for g in cfg.get('rules_glob') or []:
        files += glob.glob(os.path.expanduser(g))
    if not files:
        print('set "rules_glob" in .claude/said-and-done.json')
        return 1
    enforced, words = [], []
    for f in sorted(files):
        t = open(f, encoding='utf-8').read()
        tools = set(re.findall(r'[\w./-]+\.(?:py|js|sh|ps1)\b', t))
        real = [x for x in tools if any(
            glob.glob(os.path.join(root, d, '**', os.path.basename(x)), recursive=True)
            for d in (cfg.get('enforcers_dir') or ['.']))]
        (enforced if real else words).append((os.path.basename(f), sorted(real)))
    print('%d rules: %d with an enforcing script, %d only words' % (len(files), len(enforced), len(words)))
    for name, real in enforced:
        print('  enforced  %-45s %s' % (name, ', '.join(real)[:70]))
    for name, _ in words:
        print('  words     ' + name)
    return 0


def cmd_selftest():
    """Cases that must pass and cases that must fail; exit 1 if any expectation is wrong."""
    bad = 0
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, '.claude'))
        with open(os.path.join(d, '.claude', 'said-and-done.json'), 'w', encoding='utf-8') as f:
            json.dump({'ledger': 'DECISIONES.md', 'lang': 'es', 'user': 'Ana', 'user_label': 'Ana'}, f)
        cfg = load_config(d)
        ledger = cfg['ledger_path']
        good = ('# x\n\n## D-0001 · 2026-10-21 · Prueba\n- **Ana:** «Sí, arma lo nuestro con las tres ideas»\n'
                '- **Propuesta aceptada:** «el guardia»\n- **Aplicada en:** PENDIENTE\n')

        def transcript(prompt, reply='', when='2026-10-21T10:00:00Z'):
            p = os.path.join(d, 't.jsonl')
            rows = [{'type': 'user', 'timestamp': '2026-10-21T09:00:00Z', 'message': {'content': 'hola'}},
                    {'type': 'user', 'timestamp': when, 'message': {'content': prompt}},
                    {'type': 'user', 'isMeta': True, 'timestamp': when, 'message': {'content': 'Sí, meta'}},
                    {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': reply}]}}]
            with open(p, 'w', encoding='utf-8') as f:
                f.write('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
            return p

        def ledger_at(epoch):
            with open(ledger, 'w', encoding='utf-8') as f:
                f.write(good)
            os.utime(ledger, (epoch, epoch))

        t_prompt = datetime(2026, 10, 21, 10, tzinfo=timezone.utc).timestamp()
        cases = [
            ('acojo + registro intacto -> BLOQUEA', 'Y acojo tus propuestas', '', t_prompt - 60, False, True),
            ('sí al inicio + registro intacto -> BLOQUEA', 'Sí, arma lo nuestro', '', t_prompt - 60, False, True),
            ('aprobación + registro cambiado -> pasa', 'Y acojo tus propuestas', '', t_prompt + 5, False, False),
            ('sin aprobación -> pasa', '¿Cuántas veces has visto esa respuesta?', '', t_prompt - 60, False, False),
            ('escape en la respuesta -> pasa', 'Procede', 'Sin decisión que registrar: solo pidió seguir.', t_prompt - 60, False, False),
            ('segundo intento tras bloquear -> pasa y se anota', 'Procede', '', t_prompt - 60, True, False),
            ('meta del sistema no cuenta -> pasa', 'pregunta suelta', '', t_prompt - 60, False, False),
        ]
        for name, prompt, reply, mtime, active, expect in cases:
            ledger_at(mtime)
            got, why = guard_decision({'transcript_path': transcript(prompt, reply), 'stop_hook_active': active}, cfg)
            ok = got == expect
            bad += not ok
            print('%s  %s (%s)' % ('ok  ' if ok else 'FAIL', name, why))
        ledger_at(t_prompt)
        _, errs = parse_ledger(ledger, cfg)
        ok = not errs
        bad += not ok
        print('%s  registro bien formado -> sin errores' % ('ok  ' if ok else 'FAIL'))
        with open(ledger, 'w', encoding='utf-8') as f:
            f.write(good.replace('- **Aplicada en:** PENDIENTE\n', ''))
        _, errs = parse_ledger(ledger, cfg)
        ok = bool(errs)
        bad += not ok
        print('%s  registro sin «Aplicada en» -> DEBE fallar (%s)' % ('ok  ' if ok else 'FAIL', errs[:1]))
        ok = is_pending('`a.md` | PENDIENTE', cfg) and is_pending('PENDIENTE', cfg) and not is_pending('`a.md`', cfg)
        bad += not ok
        print('%s  aplicada a medias (`a.md` | PENDIENTE) -> cuenta como pendiente' % ('ok  ' if ok else 'FAIL'))
        frags = quote_fragments('«Y acojo tus propuestas»; esa noche: «Recuerda que dijimos que trabajamos [...] serializada»')
        ok = norm('Suspende... Y acojo tus propuestas. Ve con Fable') .find(frags[0]) >= 0
        bad += not ok
        print('%s  el repaso reconoce la cita dentro del mensaje' % ('ok  ' if ok else 'FAIL'))
    print('selftest: %s' % ('OK' if not bad else '%d FAILED' % bad))
    return 1 if bad else 0


def main():
    root = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if cmd == 'guard':
        return cmd_guard(root)
    if cmd == 'check':
        return cmd_check(root)
    if cmd == 'review':
        return cmd_review(root, sys.argv[2:])
    if cmd == 'audit':
        return cmd_audit(root)
    if cmd == 'selftest':
        return cmd_selftest()
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
