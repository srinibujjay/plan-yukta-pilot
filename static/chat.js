(function () {
  const root = document.getElementById('py-chat');
  if (!root) return;
  const panel = root.querySelector('.chat-panel');
  const log = root.querySelector('.chat-log');
  const form = root.querySelector('form');
  const input = form.querySelector('textarea');
  const ctxEl = document.getElementById('py-context');
  const context = ctxEl ? ctxEl.textContent : '';
  const history = [];

  function esc(t) { return t.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function render(t) {
    return esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .split(/\n/).map(l => /^\s*[-•]\s+/.test(l) ? '<li>' + l.replace(/^\s*[-•]\s+/, '') + '</li>' : l).join('\n')
      .replace(/(<li>.*<\/li>\n?)+/g, m => '<ul>' + m.replace(/\n/g, '') + '</ul>')
      .replace(/\n/g, '<br>');
  }
  function add(role, text, mode) {
    const d = document.createElement('div');
    d.className = 'msg ' + role;
    d.innerHTML = render(text) + (mode === 'help' ? '<div class="mode">From the help pages</div>' : '');
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }
  root.querySelector('.chat-open').addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });
  root.querySelector('.chat-close').addEventListener('click', () => { panel.hidden = true; });
  root.querySelectorAll('.chip').forEach(b => b.addEventListener('click', () => { input.value = b.textContent; form.requestSubmit(); }));
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
