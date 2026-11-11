/* Plan Yukta data grid editor: edit, add, duplicate, delete, filter, sort, save with validation */
(function () {
  const el = document.getElementById('dg-payload');
  if (!el) return;
  const P = JSON.parse(el.textContent);
  const cols = P.columns;
  const keyed = P.keyed;
  const PAGE = 100;
  let rows = P.rows.map((r, i) => ({ id: i + 1, v: Object.assign({}, r), o: Object.assign({}, r), added: false }));
  let nextId = rows.length + 1;
  let deleted = 0, page = 0, filter = '', errors = {}, sortCol = null, sortDir = 1;
  const $ = s => document.querySelector(s);
  const table = $('#dg'), body = table.querySelector('tbody'), status = $('#dg-status'), errBox = $('#dg-errors');

  const colFor = (r, c) => (keyed && c.name === 'Value') ? Object.assign({}, c, P.settingCols[r.v.Setting] || {}) : c;
  const isNum = c => ['int', 'num', 'frac'].includes(c.type);
  const show = v => (v === null || v === undefined) ? '' : String(v);
  const dirty = () => deleted > 0 || rows.some(r => r.added || cols.some(c => show(r.v[c.name]) !== show(r.o[c.name])));

  function setStatus() {
    const d = dirty();
    status.className = 'dg-status' + (d ? ' dirty' : '');
    status.textContent = d ? 'Unsaved changes' : (status.dataset.saved || `${rows.length.toLocaleString()} rows`);
    $('#dg-save').disabled = !d;
    $('#dg-undo').disabled = !d;
  }

  function visible() {
    const q = filter.toLowerCase();
    return rows.filter(r => !q || cols.some(c => show(r.v[c.name]).toLowerCase().includes(q)));
  }

  function placeholder(c) {
    return { month: 'YYYY-MM', date: 'YYYY-MM-DD', frac: '0-1', int: '0', num: '0' }[c.type] || '';
  }

  function render() {
    const vis = visible();
    const pages = Math.max(1, Math.ceil(vis.length / PAGE));
    page = Math.min(page, pages - 1);
    const slice = vis.slice(page * PAGE, page * PAGE + PAGE);
    body.innerHTML = '';
    slice.forEach(r => {
      const tr = document.createElement('tr');
      if (r.added) tr.className = 'added';
      tr.dataset.id = r.id;
      const sel = document.createElement('td');
      sel.className = 'sel';
      if (!keyed) sel.innerHTML = `<input type="checkbox" aria-label="Select row ${r.id}">`;
      tr.appendChild(sel);
      const rn = document.createElement('td');
      rn.className = 'rn';
      rn.textContent = r.id;
      tr.appendChild(rn);
      cols.forEach(c0 => {
        const c = colFor(r, c0);
        const td = document.createElement('td');
        td.dataset.col = c0.name;
        const v = r.v[c0.name];
        if (c0.readonly) {
          td.className = 'ro';
          td.textContent = show(v);
          td.title = c0.name === 'Notes' ? show(v) : '';
        } else if (c.type === 'choice') {
          const s = document.createElement('select');
          const opts = (c.required ? [] : ['']).concat(c.choices);
          if (v !== null && v !== '' && !opts.includes(String(v))) opts.unshift(String(v));
          if (c.required && (v === null || v === '')) opts.unshift('');
          s.innerHTML = opts.map(o => `<option${String(o) === show(v) ? ' selected' : ''}>${o}</option>`).join('');
          s.addEventListener('change', () => update(r, c0.name, s.value, td));
          td.appendChild(s);
        } else {
          const inp = document.createElement('input');
          inp.value = show(v);
          inp.placeholder = placeholder(c);
          if (isNum(c)) inp.className = 'n';
          inp.setAttribute('aria-label', c0.name);
          inp.addEventListener('input', () => update(r, c0.name, inp.value, td));
          td.appendChild(inp);
        }
        if (!r.added && show(r.v[c0.name]) !== show(r.o[c0.name])) td.classList.add('changed');
        const e = errors[r.id] && errors[r.id][c0.name];
        if (e) { td.classList.add('err'); td.title = e; }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    $('#dg-page').textContent = vis.length ? `Rows ${(page * PAGE + 1).toLocaleString()}–${Math.min(vis.length, page * PAGE + PAGE).toLocaleString()} of ${vis.length.toLocaleString()}${filter ? ' (filtered)' : ''}` : 'No rows';
    $('#dg-prev').disabled = page === 0;
    $('#dg-next').disabled = page >= pages - 1;
    setStatus();
  }

  function update(r, name, value, td) {
    r.v[name] = value === '' ? null : value;
    if (!r.added) td.classList.toggle('changed', show(r.v[name]) !== show(r.o[name]));
    if (errors[r.id]) { delete errors[r.id][name]; td.classList.remove('err'); td.title = ''; }
    status.dataset.saved = '';
    setStatus();
  }

  function selected() {
    return Array.from(body.querySelectorAll('input[type=checkbox]:checked')).map(cb => +cb.closest('tr').dataset.id);
  }

  $('#dg-add') && $('#dg-add').addEventListener('click', () => {
    const v = {};
    cols.forEach(c => { v[c.name] = null; });
    rows.push({ id: nextId++, v, o: {}, added: true });
    filter = ''; $('#dg-filter').value = '';
    page = Math.ceil(rows.length / PAGE) - 1;
    render();
    const last = body.lastElementChild;
    if (last) { const f = last.querySelector('input:not([type=checkbox]), select'); if (f) f.focus(); last.scrollIntoView({ block: 'center' }); }
  });
  $('#dg-dup') && $('#dg-dup').addEventListener('click', () => {
    const ids = selected();
    if (!ids.length) { alertBox('Tick one or more rows to duplicate.'); return; }
    ids.forEach(id => { const r = rows.find(x => x.id === id); rows.push({ id: nextId++, v: Object.assign({}, r.v), o: {}, added: true }); });
    page = Math.ceil(rows.length / PAGE) - 1;
    render();
    alertBox(`${ids.length} row(s) duplicated at the end. Change the key columns so each row is unique.`, 'info');
  });
  $('#dg-del') && $('#dg-del').addEventListener('click', () => {
    const ids = selected();
    if (!ids.length) { alertBox('Tick the rows to delete first.'); return; }
    rows = rows.filter(r => { if (ids.includes(r.id)) { if (!r.added) deleted++; return false; } return true; });
    render();
  });
  $('#dg-undo').addEventListener('click', () => { if (confirm('Discard your unsaved changes?')) { window.onbeforeunload = null; location.reload(); } });
  $('#dg-filter').addEventListener('input', e => { filter = e.target.value.trim(); page = 0; render(); });
  $('#dg-prev').addEventListener('click', () => { page--; render(); });
  $('#dg-next').addEventListener('click', () => { page++; render(); });
  $$('#dg thead th[data-col]').forEach(th => th.addEventListener('click', () => {
    const name = th.dataset.col;
    sortDir = sortCol === name ? -sortDir : 1;
    sortCol = name;
    const c = cols.find(x => x.name === name);
    rows.sort((a, b) => {
      let x = a.v[name], y = b.v[name];
      if (isNum(c)) { x = parseFloat(x); y = parseFloat(y); x = isNaN(x) ? -Infinity : x; y = isNaN(y) ? -Infinity : y; }
      else { x = show(x).toLowerCase(); y = show(y).toLowerCase(); }
      return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
    });
    render();
  }));
  function $$(s) { return Array.from(document.querySelectorAll(s)); }

  function alertBox(msg, tone) {
    errBox.innerHTML = `<div class="callout ${tone || 'warn'}">${msg}</div>`;
  }

  $('#dg-save').addEventListener('click', async () => {
    const btn = $('#dg-save');
    btn.disabled = true;
    status.textContent = 'Saving and re-planning…';
    errors = {};
    const payloadRows = rows.map(r => r.v);
    try {
      const res = await fetch(P.save, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: payloadRows }) });
      const data = await res.json();
      if (data.ok) {
        rows = rows.map(r => ({ id: r.id, v: r.v, o: Object.assign({}, r.v), added: false }));
        deleted = 0;
        status.dataset.saved = `Saved ${data.rows.toLocaleString()} rows · plan recalculated`;
        errBox.innerHTML = `<div class="callout ok">Saved. Every module now uses this data. ${P.links || ''}</div>`;
        render();
        status.className = 'dg-status saved';
      } else {
        const list = [];
        (data.errors || []).forEach(([i, col, msg]) => {
          const r = rows[i];
          if (!r) { list.push(msg); return; }
          (errors[r.id] = errors[r.id] || {})[col || cols[0].name] = msg;
          list.push(`<a href="#" data-goto="${r.id}">Row ${r.id}</a> · <b>${col || ''}</b>: ${msg}`);
        });
        errBox.innerHTML = `<div class="callout bad"><b>Not saved: ${data.count || list.length} problem(s).</b> Fix the red cells and save again.<br>${list.slice(0, 15).join('<br>')}${list.length > 15 ? '<br>…' : ''}</div>`;
        errBox.querySelectorAll('[data-goto]').forEach(a => a.addEventListener('click', e => {
          e.preventDefault();
          const id = +a.dataset.goto;
          filter = ''; $('#dg-filter').value = '';
          page = Math.floor(rows.findIndex(r => r.id === id) / PAGE);
          render();
          const tr = body.querySelector(`tr[data-id="${id}"]`);
          if (tr) { tr.scrollIntoView({ block: 'center' }); const c = tr.querySelector('td.err input, td.err select'); if (c) c.focus(); }
        }));
        render();
      }
    } catch (e) {
      alertBox('Could not reach the server. Your changes are still here; try Save again.', 'bad');
      setStatus();
    }
  });

  window.addEventListener('beforeunload', e => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });
  document.querySelectorAll('form[data-confirm]').forEach(f => f.addEventListener('submit', e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); else window.onbeforeunload = null; }));
  render();
})();
