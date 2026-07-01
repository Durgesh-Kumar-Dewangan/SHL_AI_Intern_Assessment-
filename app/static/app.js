/* SHL Assessment Recommender – Frontend */

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  messages: [],         // full conversation history sent to API
  allRecs: [],          // current recommendation list
  catalogItems: [],     // fetched once
  historyLog: [],       // saved conversations
};

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setWelcomeTime();
  checkHealth();
  fetchCatalog();
  setInterval(checkHealth, 30000);
  initCfgTrigger();
});

function setWelcomeTime() {
  const el = document.getElementById('welcome-time');
  if (el) el.textContent = fmtTime(new Date());
}

// ─── Tab Switching ────────────────────────────────────────────────────────────
function showTab(name, el) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pane = document.getElementById('tab-' + name);
  if (pane) pane.classList.add('active');
  if (el) el.classList.add('active');

  if (name === 'catalog' && state.catalogItems.length > 0) renderCatalogGrid(state.catalogItems);
  if (name === 'history') renderHistory();
}

// ─── Health Check ─────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = document.getElementById('status-dot');
  const label = document.getElementById('status-label');
  const badge = document.getElementById('health-badge');
  try {
    const r = await fetch('/health');
    if (r.ok) {
      dot.className = 'status-dot online';
      label.textContent = 'Online';
      badge.textContent = '/health OK';
      badge.style.background = '#166534';
      badge.style.color = '#86efac';
    } else { throw new Error(); }
  } catch {
    dot.className = 'status-dot offline';
    label.textContent = 'Offline';
    badge.textContent = '/health ERR';
    badge.style.background = '#7f1d1d';
    badge.style.color = '#fca5a5';
  }
}

// ─── Fetch Catalog ────────────────────────────────────────────────────────────
async function fetchCatalog() {
  try {
    const r = await fetch('/catalog?limit=400');
    if (!r.ok) return;
    const data = await r.json();
    state.catalogItems = data.items || [];
    const countEl = document.getElementById('catalog-count');
    const totalEl = document.getElementById('cat-total');
    if (countEl) countEl.textContent = data.total || state.catalogItems.length;
    if (totalEl) totalEl.textContent = data.total || state.catalogItems.length;
    const modelEl = document.getElementById('model-name');
    if (modelEl && data.model) modelEl.textContent = data.model;
  } catch (e) { console.error('Catalog fetch failed:', e); }
}

// ─── Chat ─────────────────────────────────────────────────────────────────────
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
}

function autoResize(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
}

async function sendMessage() {
  const input = document.getElementById('user-input');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.style.height = 'auto';
  setButtonLoading(true);

  appendMessage('user', text);
  state.messages.push({ role: 'user', content: text });

  const thinkId = appendThinking();

  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: state.messages }),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(err);
    }

    const data = await response.json();
    removeThinking(thinkId);

    const reply = data.reply || '';
    const recs = data.recommendations || null;
    const eoc = data.end_of_conversation || false;

    state.messages.push({ role: 'assistant', content: reply });

    if (recs && recs.length > 0) {
      state.allRecs = recs;
      appendMessageWithRecs('assistant', reply, recs);
      updateRecsPanel(recs);
    } else {
      appendMessage('assistant', reply);
    }

    if (eoc) {
      setTimeout(() => appendMessage('assistant', '✓ Conversation complete. Feel free to start a new one or refine your requirements.'), 400);
    }

    scrollToBottom();
  } catch (err) {
    removeThinking(thinkId);
    appendMessage('assistant', '⚠️ Error: ' + (err.message || 'Could not reach the server. Please try again.'));
  } finally {
    setButtonLoading(false);
  }
}

function setButtonLoading(loading) {
  const btn = document.getElementById('send-btn');
  btn.disabled = loading;
}

function appendMessage(role, text) {
  const messages = document.getElementById('messages');
  const isUser = role === 'user';
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.innerHTML = `
    <div class="msg-avatar ${isUser ? 'user-avatar' : 'ai-avatar'}">${isUser ? 'You' : 'SHL<br>AI'}</div>
    <div class="msg-body">
      <div class="msg-bubble">${escapeHtml(text).replace(/\n/g, '<br>')}</div>
      <div class="msg-time">${fmtTime(new Date())}</div>
    </div>`;
  messages.appendChild(el);
  scrollToBottom();
  return el;
}

function appendMessageWithRecs(role, text, recs) {
  const messages = document.getElementById('messages');
  const shown = recs.slice(0, 3);
  const extra = recs.slice(3);

  const recsHtml = shown.map((r, i) => `
    <div class="inline-rec">
      <span class="inline-rec-num">${i + 1}</span>
      <span class="inline-rec-name">${escapeHtml(r.name)}</span>
      <span class="inline-rec-type ${typeClass(r.test_type)}">${typeLabel(r.test_type)}</span>
      <a href="${r.url}" target="_blank" class="inline-rec-link">View ↗</a>
    </div>`).join('');

  const moreHtml = extra.length > 0
    ? `<button class="show-more-btn" onclick="this.parentElement.querySelector('.extra-recs').style.display='flex'; this.style.display='none';">Show ${extra.length} more ▾</button>
       <div class="inline-recs extra-recs" style="display:none">${extra.map((r, i) => `
         <div class="inline-rec">
           <span class="inline-rec-num">${shown.length + i + 1}</span>
           <span class="inline-rec-name">${escapeHtml(r.name)}</span>
           <span class="inline-rec-type ${typeClass(r.test_type)}">${typeLabel(r.test_type)}</span>
           <a href="${r.url}" target="_blank" class="inline-rec-link">View ↗</a>
         </div>`).join('')}</div>`
    : '';

  const el = document.createElement('div');
  el.className = 'msg assistant';
  el.innerHTML = `
    <div class="msg-avatar ai-avatar">SHL<br>AI</div>
    <div class="msg-body">
      <div class="msg-bubble">
        ${escapeHtml(text).replace(/\n/g, '<br>')}
        <div class="inline-recs">${recsHtml}</div>
        ${moreHtml}
      </div>
      <div class="msg-time">${fmtTime(new Date())}</div>
    </div>`;
  messages.appendChild(el);
  scrollToBottom();
}

let thinkingCounter = 0;
function appendThinking() {
  const id = 'thinking-' + (++thinkingCounter);
  const messages = document.getElementById('messages');
  const el = document.createElement('div');
  el.className = 'msg assistant thinking';
  el.id = id;
  el.innerHTML = `
    <div class="msg-avatar ai-avatar">SHL<br>AI</div>
    <div class="msg-body">
      <div class="msg-bubble">
        <span class="thinking-dots"><span>●</span><span>●</span><span>●</span></span>
      </div>
    </div>`;
  messages.appendChild(el);
  scrollToBottom();
  return id;
}

function removeThinking(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function scrollToBottom() {
  const messages = document.getElementById('messages');
  messages.scrollTop = messages.scrollHeight;
}

function clearChat() {
  if (state.messages.length > 0) {
    state.historyLog.push({
      id: Date.now(),
      messages: [...state.messages],
      recs: [...state.allRecs],
      time: new Date().toLocaleString(),
    });
  }
  state.messages = [];
  state.allRecs = [];
  const messages = document.getElementById('messages');
  messages.innerHTML = `
    <div class="msg assistant">
      <div class="msg-avatar ai-avatar">SHL<br>AI</div>
      <div class="msg-body">
        <div class="msg-bubble">
          Welcome! I'm your SHL Assessment Recommender. Tell me about the role you're hiring for and I'll help you find the right assessments.
          <p class="msg-examples">Try: <em>"I'm hiring a Java developer"</em> or <em>"Need cognitive tests for graduate intake"</em></p>
        </div>
        <div class="msg-time">${fmtTime(new Date())}</div>
      </div>
    </div>`;
  resetRecsPanel();
}

// ─── Recommendations Panel ────────────────────────────────────────────────────
function updateRecsPanel(recs) {
  const list = document.getElementById('recs-list');
  const countEl = document.getElementById('recs-count');
  const viewAllBtn = document.getElementById('view-all-btn');
  const compareCard = document.getElementById('compare-card');

  countEl.textContent = recs.length;
  viewAllBtn.style.display = recs.length > 5 ? 'block' : 'none';

  const shown = recs.slice(0, 5);
  list.innerHTML = shown.map((r, i) => `
    <div class="rec-item">
      <span class="rec-num">${i + 1}</span>
      <span class="rec-name" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</span>
      <span class="rec-type-badge ${typeClass(r.test_type)}">${typeLabel(r.test_type)}</span>
      <a href="${r.url}" target="_blank" class="rec-link" title="View on SHL.com">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </a>
    </div>`).join('');

  // Show compare card for 2+ recs
  if (recs.length >= 2) {
    compareCard.style.display = 'block';
    document.getElementById('compare-subtitle').textContent = `${recs[0].name} vs ${recs[1].name}`;
    renderCompareTable(recs[0], recs[1]);
  }
}

function showAllRecs() {
  const list = document.getElementById('recs-list');
  const recs = state.allRecs;
  document.getElementById('view-all-btn').style.display = 'none';
  list.innerHTML = recs.map((r, i) => `
    <div class="rec-item">
      <span class="rec-num">${i + 1}</span>
      <span class="rec-name" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</span>
      <span class="rec-type-badge ${typeClass(r.test_type)}">${typeLabel(r.test_type)}</span>
      <a href="${r.url}" target="_blank" class="rec-link">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </a>
    </div>`).join('');
}

function resetRecsPanel() {
  document.getElementById('recs-list').innerHTML = `
    <div class="recs-empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
      <p>Recommendations will appear here after the conversation</p>
    </div>`;
  document.getElementById('recs-count').textContent = '';
  document.getElementById('view-all-btn').style.display = 'none';
  document.getElementById('compare-card').style.display = 'none';
}

// ─── Compare Table ────────────────────────────────────────────────────────────
function renderCompareTable(a, b) {
  const wrap = document.getElementById('compare-table-wrap');
  const rows = [
    ['Name', escapeHtml(a.name), escapeHtml(b.name)],
    ['Test Type', typeLabel(a.test_type), typeLabel(b.test_type)],
    ['URL', `<a href="${a.url}" target="_blank" style="color:#2563eb;font-size:10px">View ↗</a>`, `<a href="${b.url}" target="_blank" style="color:#2563eb;font-size:10px">View ↗</a>`],
  ];
  wrap.innerHTML = `<table class="compare-table">
    <thead><tr><th>Aspect</th><th>${escapeHtml(a.name.substring(0, 18))}</th><th>${escapeHtml(b.name.substring(0, 18))}</th></tr></thead>
    <tbody>${rows.map(([asp, va, vb]) => `<tr><td><strong>${asp}</strong></td><td>${va}</td><td>${vb}</td></tr>`).join('')}</tbody>
  </table>`;
}

// ─── Compare Tab ─────────────────────────────────────────────────────────────
async function runCompare() {
  const a = document.getElementById('cmp-a').value.trim();
  const b = document.getElementById('cmp-b').value.trim();
  const result = document.getElementById('compare-result');
  if (!a || !b) { result.innerHTML = '<p style="color:#ef4444">Please enter both assessment names.</p>'; return; }

  result.innerHTML = '<p style="color:#94a3b8">Asking the assistant to compare…</p>';

  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: `What is the difference between ${a} and ${b}?` }] }),
    });
    const data = await r.json();
    result.innerHTML = `<div class="msg assistant" style="margin-top:12px">
      <div class="msg-avatar ai-avatar">SHL<br>AI</div>
      <div class="msg-body"><div class="msg-bubble">${escapeHtml(data.reply || '').replace(/\n/g, '<br>')}</div></div>
    </div>`;
  } catch (e) {
    result.innerHTML = '<p style="color:#ef4444">Error contacting API.</p>';
  }
}

// ─── Catalog Tab ─────────────────────────────────────────────────────────────
function filterCatalog() {
  const q = document.getElementById('cat-search').value.toLowerCase();
  const type = document.getElementById('cat-type-filter').value;
  let filtered = state.catalogItems;
  if (q) filtered = filtered.filter(item =>
    item.name.toLowerCase().includes(q) || (item.description || '').toLowerCase().includes(q)
  );
  if (type) filtered = filtered.filter(item =>
    item.test_type_codes && item.test_type_codes.includes(type)
  );
  renderCatalogGrid(filtered);
}

function renderCatalogGrid(items) {
  const grid = document.getElementById('catalog-grid');
  if (!grid) return;
  if (items.length === 0) {
    grid.innerHTML = '<p style="color:#94a3b8;padding:20px">No assessments match your search.</p>';
    return;
  }
  grid.innerHTML = items.slice(0, 120).map(item => {
    const typeCode = item.test_type_codes && item.test_type_codes[0] || '';
    const duration = item.duration_display || (item.duration_minutes ? item.duration_minutes + ' mins' : 'Variable');
    const desc = (item.description || '').substring(0, 120) + ((item.description || '').length > 120 ? '…' : '');
    return `<div class="cat-card">
      <div class="cat-card-header">
        <span class="cat-card-name">${escapeHtml(item.name)}</span>
        <span class="cat-card-type ${typeClass(typeCode)}">${typeLabel(typeCode)}</span>
      </div>
      <div class="cat-card-desc">${escapeHtml(desc)}</div>
      <div class="cat-card-meta">
        <span class="cat-meta-item">${escapeHtml(duration)}</span>
        ${item.remote_testing ? '<span class="cat-meta-item">Remote</span>' : ''}
        ${item.adaptive ? '<span class="cat-meta-item">Adaptive</span>' : ''}
      </div>
      <a href="${item.url}" target="_blank" class="cat-card-link">View on SHL.com ↗</a>
    </div>`;
  }).join('');
}

// ─── History Tab ──────────────────────────────────────────────────────────────
function renderHistory() {
  const list = document.getElementById('history-list');
  if (state.historyLog.length === 0) {
    list.innerHTML = `<div class="empty-state">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      <p>No conversation history yet. Start a chat to see it here.</p>
    </div>`;
    return;
  }
  list.innerHTML = state.historyLog.slice().reverse().map(h => `
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;margin-bottom:8px">
        <strong style="font-size:13px">${h.messages[0]?.content?.substring(0, 60) || 'Conversation'}</strong>
        <span style="font-size:11px;color:#94a3b8">${h.time}</span>
      </div>
      <div style="font-size:12px;color:#64748b">${h.messages.length} messages · ${h.recs.length} recommendations</div>
    </div>`).join('');
}

// ─── API Explorer ─────────────────────────────────────────────────────────────
async function callHealth() {
  const el = document.getElementById('health-response');
  el.classList.add('visible');
  el.textContent = 'Sending request…';
  try {
    const r = await fetch('/health');
    const data = await r.json();
    el.textContent = `HTTP ${r.status} OK\n\n${JSON.stringify(data, null, 2)}`;
    el.style.color = '#86efac';
  } catch (e) {
    el.textContent = 'Error: ' + e.message;
    el.style.color = '#fca5a5';
  }
}

async function callChat() {
  const el = document.getElementById('chat-response');
  el.classList.add('visible');
  el.textContent = 'Sending request…';
  el.style.color = '#e2e8f0';
  try {
    const payload = JSON.parse(document.getElementById('chat-payload').value);
    const r = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    el.textContent = `HTTP ${r.status}\n\n${JSON.stringify(data, null, 2)}`;
    el.style.color = r.ok ? '#86efac' : '#fca5a5';
  } catch (e) {
    el.textContent = 'Error: ' + e.message;
    el.style.color = '#fca5a5';
  }
}

async function callCatalog() {
  const el = document.getElementById('catalog-response');
  el.classList.add('visible');
  el.textContent = 'Sending request…';
  el.style.color = '#e2e8f0';
  const q = document.getElementById('catalog-q').value;
  const type = document.getElementById('catalog-type').value;
  const limit = document.getElementById('catalog-limit').value;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (type) params.set('type', type);
  if (limit) params.set('limit', limit);
  try {
    const r = await fetch('/catalog?' + params.toString());
    const data = await r.json();
    el.textContent = `HTTP ${r.status}\n\n${JSON.stringify(data, null, 2)}`;
    el.style.color = r.ok ? '#86efac' : '#fca5a5';
  } catch (e) {
    el.textContent = 'Error: ' + e.message;
    el.style.color = '#fca5a5';
  }
}

// ─── Hidden Config Panel ──────────────────────────────────────────────────────
function initCfgTrigger() {
  const logo = document.querySelector('.brand-logo-wrap');
  if (!logo) return;
  let clicks = 0, timer = null;
  logo.addEventListener('click', () => {
    clicks++;
    if (clicks >= 3) { clicks = 0; clearTimeout(timer); openCfg(); return; }
    clearTimeout(timer);
    timer = setTimeout(() => { clicks = 0; }, 600);
  });
}

async function openCfg() {
  try {
    const r = await fetch('/admin/settings');
    const d = await r.json();
    document.getElementById('cfg-provider').value = d.llm_provider || 'groq';
    document.getElementById('cfg-model').value = d.llm_model || '';
    document.getElementById('cfg-temp').value = d.llm_temperature ?? 0.2;
    document.getElementById('cfg-tokens').value = d.llm_max_tokens ?? 900;
    document.getElementById('cfg-key').value = '';
    document.getElementById('cfg-msg').textContent = '';
    document.getElementById('cfg-msg').className = '';
  } catch(e) {}
  document.getElementById('cfg-overlay').classList.add('open');
  document.getElementById('cfg-panel').classList.add('open');
}

function closeCfg() {
  document.getElementById('cfg-overlay').classList.remove('open');
  document.getElementById('cfg-panel').classList.remove('open');
}

async function saveCfg() {
  const btn = document.getElementById('cfg-save');
  const msg = document.getElementById('cfg-msg');
  btn.disabled = true;
  btn.textContent = '…';
  msg.textContent = '';
  const payload = {
    llm_provider: document.getElementById('cfg-provider').value,
    llm_model: document.getElementById('cfg-model').value.trim(),
    llm_api_key: document.getElementById('cfg-key').value.trim(),
    llm_temperature: parseFloat(document.getElementById('cfg-temp').value) || null,
    llm_max_tokens: parseInt(document.getElementById('cfg-tokens').value) || null,
  };
  try {
    const r = await fetch('/admin/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (d.ok) {
      msg.textContent = 'Saved';
      msg.className = 'ok';
      const el = document.getElementById('model-name');
      if (el) el.textContent = `${d.llm_provider} / ${d.llm_model}`;
      setTimeout(closeCfg, 900);
    } else {
      msg.textContent = 'Error saving';
      msg.className = 'err';
    }
  } catch(e) {
    msg.textContent = 'Request failed';
    msg.className = 'err';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Apply';
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function typeLabel(typeStr) {
  if (!typeStr) return 'Other';
  const codes = typeStr.split(',').map(s => s.trim());
  const labels = { A: 'Cognitive', B: 'Exercise', C: 'Situational', K: 'Technical', P: 'Personality', S: 'Simulation', D: 'Development', E: 'Emotional' };
  const first = codes[0];
  return labels[first] || first || 'Other';
}

function typeClass(typeStr) {
  if (!typeStr) return 'type-A';
  const first = typeStr.split(',')[0].trim();
  return 'type-' + (first || 'A');
}
