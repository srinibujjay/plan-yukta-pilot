/* Plan Yukta cockpit: navigation, theme, table filter/sort, and the chat assistant */
(function () {
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  };

  // theme
  const tb = $('#theme-btn');
  if (tb) tb.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    store.set('py-theme', next);
  });

  // mobile sidebar
  const sb = $('#sidebar'), scrim = $('#scrim'), mb = $('#menu-btn');
  const toggle = open => { sb.classList.toggle('open', open); scrim.classList.toggle('open', open); };
  if (mb) mb.addEventListener('click', () => toggle(!sb.classList.contains('open')));
  if (scrim) scrim.addEventListener('click', () => toggle(false));

  // collapsible nav groups (remembered); the group holding the current page stays open
  let closed = {};
  try { closed = JSON.parse(store.get('py-nav') || '{}'); } catch (e) { closed = {}; }
  $$('.nav-group').forEach(g => {
    const name = g.dataset.group, head = $('.nav-head', g);
    const hasOn = !!$('.nav-item.on', g);
    if (closed[name] && !hasOn) { g.classList.add('closed'); head.setAttribute('aria-expanded', 'false'); }
    head.addEventListener('click', () => {
      const c = g.classList.toggle('closed');
      head.setAttribute('aria-expanded', c ? 'false' : 'true');
      closed[name] = c;
      store.set('py-nav', JSON.stringify(closed));
    });
  });
  const on = $('.nav-item.on');
  if (on && sb && on.offsetTop > sb.clientHeight - 120) sb.scrollTop = on.offsetTop - 160;

  // table filter
  $$('input[data-filter]').forEach(inp => {
    const t = document.getElementById('t-' + inp.dataset.filter);
    if (!t) return;
    inp.addEventListener('input', () => {
      const q = inp.value.trim().toLowerCase();
      $$('tbody tr', t).forEach(tr => { tr.style.display = !q || tr.textContent.toLowerCase().includes(q) ? '' : 'none'; });
    });
  });

  // table sort
  $$('table.sortable-table').forEach(t => {
    $$('th.sortable', t).forEach(th => th.addEventListener('click', () => {
      const i = +th.dataset.col, body = $('tbody', t), rows = $$('tr', body);
      const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
      $$('th', t).forEach(x => delete x.dataset.dir);
      th.dataset.dir = dir;
      const val = tr => { const td = tr.children[i]; const v = td ? (td.dataset.v ?? td.textContent) : ''; const n = parseFloat(String(v).replace(/[$,%]/g, '')); return isNaN(n) ? String(v).toLowerCase() : n; };
      rows.sort((a, b) => { const x = val(a), y = val(b); return (x > y ? 1 : x < y ? -1 : 0) * (dir === 'asc' ? 1 : -1); });
      rows.forEach(r => body.appendChild(r));
    }));
  });

  // chat
  const root = $('#py-chat');
  if (!root) return;
  const panel = $('.chat-panel', root), log = $('.chat-log', root), form = $('form', root), input = $('textarea', form);
  const ctxEl = $('#py-context');
  const context = ctxEl ? ctxEl.textContent : '';
  const history = [];
  const esc = t => t.replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const render = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .split(/\n/).map(l => /^\s*[-•]\s+/.test(l) ? '<li>' + l.replace(/^\s*[-•]\s+/, '') + '</li>' : l).join('\n')
    .replace(/(<li>.*<\/li>\n?)+/g, m => '<ul style="margin:4px 0;padding-left:18px">' + m.replace(/\n/g, '') + '</ul>')
    .replace(/\n/g, '<br>');
  const add = (role, text, mode) => {
    const d = document.createElement('div');
    d.className = 'msg ' + (role === 'user' ? 'me' : 'bot');
    d.innerHTML = render(text) + (mode === 'help' ? '<div class="muted small" style="margin-top:4px">From the help pages</div>' : '');
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  };
  $('.chat-open', root).addEventListener('click', () => { panel.hidden = !panel.hidden; if (!panel.hidden) input.focus(); });
  $('.chat-close', root).addEventListener('click', () => { panel.hidden = true; });
  $$('.chip', root).forEach(b => b.addEventListener('click', () => { input.value = b.textContent; form.requestSubmit(); }));
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    input.value = '';
    add('user', q);
    const wait = add('bot', 'Thinking…');
    try {
      const r = await fetch(root.dataset.url, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: q, context: context, history: history.slice(-6)})});
      const data = await r.json();
      wait.remove();
      add('bot', data.answer || data.error || 'Something went wrong.', data.mode);
      history.push({role: 'user', text: q}, {role: 'assistant', text: data.answer || ''});
    } catch (err) {
      wait.remove();
      add('bot', 'I could not reach the server. Check your connection and try again.');
    }
  });
})();
