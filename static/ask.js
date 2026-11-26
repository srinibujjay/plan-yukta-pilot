/* Ask Yukta landing chatbot: Yukta Lite answers from the server; optional on-device small model (WebLLM) in the browser. */
const WEBLLM = 'https://esm.run/@mlc-ai/web-llm@0.2.84';
const MODEL = 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC';
const SYSTEM = 'You are Yukta, an assistant for fabless semiconductor supply chain planning inside the Plan Yukta tool. ' +
  'Use the FACTS when they answer the question and copy every number, name and markdown link from them exactly; never invent figures. ' +
  'If the FACTS do not cover the question, answer briefly from general semiconductor knowledge and say it is general guidance. ' +
  'Politely decline topics unrelated to semiconductors, electronics manufacturing or supply chains. ' +
  'Write under 150 words, plain language, short bullets where useful.';

const $ = (s, r = document) => r.querySelector(s);
const root = $('#py-ask');
if (root) {
  const log = $('.ask-log', root), form = $('form', root), input = $('textarea', form), btn = $('button[type=submit]', form);
  const toggle = $('#llm-toggle'), status = $('#llm-status'), pill = $('#ask-mode');
  const render = t => (window.pyRender ? window.pyRender(t) : t.replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c])));
  const history = [];
  let engine = null, loading = null;

  const add = (role, html) => {
    const d = document.createElement('div');
    d.className = 'msg ' + (role === 'user' ? 'me' : 'bot');
    d.style.whiteSpace = 'normal';
    d.innerHTML = html;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  };
  const say = t => { status.textContent = t; };

  async function loadEngine() {
    if (engine) return engine;
    if (loading) return loading;
    if (!('gpu' in navigator)) throw new Error('This browser has no WebGPU. Use a recent Chrome or Edge on a laptop or desktop.');
    loading = (async () => {
      say('Loading the on-device model… (first time downloads about 400 MB)');
      const webllm = await import(WEBLLM);
      engine = await webllm.CreateMLCEngine(MODEL, {
        initProgressCallback: p => say(`Loading the on-device model: ${Math.round((p.progress || 0) * 100)}% · ${p.text || ''}`.slice(0, 160)),
      });
      say('On-device model ready. Answers are written in your browser; nothing is sent to an AI service.');
      pill.textContent = 'Yukta Lite + on-device AI';
      return engine;
    })();
    try { return await loading; } catch (e) { loading = null; throw e; }
  }

  toggle.addEventListener('change', async () => {
    try { localStorage.setItem('py-llm', toggle.checked ? '1' : ''); } catch (e) { /* storage blocked: fine */ }
    if (!toggle.checked) { pill.textContent = 'Yukta Lite · free, unlimited'; say('Off. Yukta Lite answers on its own.'); return; }
    try { await loadEngine(); } catch (e) { toggle.checked = false; say('Could not start on-device AI: ' + (/fetch|import|network/i.test(e.message) ? 'the model could not be downloaded (offline, or the network blocks it).' : e.message) + ' Yukta Lite still works.'); }
  });
  try { if (localStorage.getItem('py-llm') === '1') { toggle.checked = true; toggle.dispatchEvent(new Event('change')); } } catch (e) { /* ignore */ }

  document.querySelectorAll('#py-ask .chip').forEach(b => b.addEventListener('click', () => { input.value = b.textContent; form.requestSubmit(); }));
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || btn.disabled) return;
    input.value = '';
    btn.disabled = true;
    add('user', render(q));
    const bubble = add('bot', 'Thinking…');
    const useLLM = toggle.checked && engine;
    let data;
    try {
      const r = await fetch(root.dataset.url, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: q, llm: !!useLLM})});
      data = await r.json();
    } catch (err) {
      bubble.innerHTML = 'I could not reach the server. Check your connection and try again.';
      btn.disabled = false;
      return;
    }
    const lite = data.answer || data.error || 'Something went wrong.';
    const plain = ['greet', 'help', 'none'].includes(data.kind);
    if (!useLLM || plain) {
      bubble.innerHTML = render(lite);
    } else {
      try {
        const messages = [{role: 'system', content: SYSTEM}, ...history.slice(-4),
          {role: 'user', content: `FACTS:\n${data.context || lite}\n\nQUESTION: ${q}`}];
        const chunks = await engine.chat.completions.create({messages, temperature: 0.3, max_tokens: 320, stream: true});
        let reply = '';
        for await (const ch of chunks) {
          reply += ch.choices[0]?.delta?.content || '';
          bubble.innerHTML = render(reply);
          log.scrollTop = log.scrollHeight;
        }
        bubble.innerHTML = render(reply || lite) +
          '<details><summary>Exact answer from the plan data (Yukta Lite)</summary>' + render(lite) + '</details>';
        history.push({role: 'user', content: q}, {role: 'assistant', content: reply.slice(0, 1200)});
      } catch (err) {
        bubble.innerHTML = render(lite) + '<div class="muted small" style="margin-top:4px">On-device AI failed, so this is the Yukta Lite answer.</div>';
      }
    }
    log.scrollTop = log.scrollHeight;
    btn.disabled = false;
    input.focus();
  });
  input.focus();
}
