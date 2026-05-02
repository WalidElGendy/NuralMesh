"""AI User Dashboard  modern glassmorphism dark UI."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.stages.cache import get_redis_client
from app.lib.auth import verify_api_key
from app.lib.dashboard_data import get_user_stats, get_user_tier_info

router = APIRouter(tags=["user-dashboard"])

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NeuralMesh  AI Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#080b14;--surface:#0d1220;--card:#131929;--border:#1e2d45;
  --accent:#4f8ef7;--accent2:#7c3aed;--green:#10b981;--yellow:#f59e0b;
  --red:#ef4444;--text:#e2e8f0;--muted:#64748b;--font:'Inter',system-ui,sans-serif
}
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* NAV */
nav{display:flex;align-items:center;justify-content:space-between;padding:1rem 2rem;
  border-bottom:1px solid var(--border);background:rgba(13,18,32,0.8);backdrop-filter:blur(12px);
  position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:.5rem;font-weight:700;font-size:1.2rem}
.logo-icon{width:32px;height:32px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1rem}
.nav-right{display:flex;align-items:center;gap:1rem}
.tier-badge{padding:.25rem .75rem;border-radius:999px;font-size:.75rem;font-weight:600;
  background:linear-gradient(135deg,var(--accent),var(--accent2));letter-spacing:.05em;text-transform:uppercase}
.api-key-display{font-family:monospace;font-size:.75rem;color:var(--muted);
  background:var(--card);padding:.25rem .75rem;border-radius:6px;border:1px solid var(--border)}

/* LAYOUT */
.container{max-width:1200px;margin:0 auto;padding:2rem}
h1{font-size:1.75rem;font-weight:700;margin-bottom:.25rem}
.subtitle{color:var(--muted);font-size:.9rem;margin-bottom:2rem}

/* STATS GRID */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-bottom:2rem}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.5rem;
  position:relative;overflow:hidden;transition:transform .2s,border-color .2s}
.stat-card:hover{transform:translateY(-2px);border-color:var(--accent)}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.stat-card.blue::before{background:linear-gradient(90deg,var(--accent),#60a5fa)}
.stat-card.purple::before{background:linear-gradient(90deg,var(--accent2),#a78bfa)}
.stat-card.green::before{background:linear-gradient(90deg,var(--green),#34d399)}
.stat-card.yellow::before{background:linear-gradient(90deg,var(--yellow),#fcd34d)}
.stat-icon{font-size:1.5rem;margin-bottom:.75rem}
.stat-label{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.25rem}
.stat-value{font-size:2rem;font-weight:700;line-height:1}
.stat-sub{font-size:.75rem;color:var(--muted);margin-top:.25rem}

/* TWO COL */
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:2rem}
@media(max-width:768px){.two-col{grid-template-columns:1fr}}

/* PANELS */
.panel{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.5rem}
.panel-title{font-size:1rem;font-weight:600;margin-bottom:1.25rem;display:flex;align-items:center;gap:.5rem}
.panel-title .dot{width:8px;height:8px;border-radius:50%;background:var(--accent)}

/* MODEL BAR CHART */
.model-bar{margin-bottom:.75rem}
.model-bar-label{display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:.3rem}
.model-bar-name{color:var(--text)}
.model-bar-count{color:var(--muted)}
.bar-track{height:6px;background:var(--border);border-radius:3px;overflow:hidden}
.bar-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent),var(--accent2));transition:width .8s ease}

/* HISTORY TABLE */
.history-table{width:100%;border-collapse:collapse;font-size:.82rem}
.history-table th{color:var(--muted);font-weight:500;text-align:left;padding:.5rem .75rem;
  border-bottom:1px solid var(--border);text-transform:uppercase;font-size:.7rem;letter-spacing:.06em}
.history-table td{padding:.6rem .75rem;border-bottom:1px solid rgba(30,45,69,.5);vertical-align:middle}
.history-table tr:last-child td{border-bottom:none}
.history-table tr:hover td{background:rgba(79,142,247,.04)}
.model-tag{display:inline-block;padding:.15rem .5rem;border-radius:4px;font-size:.7rem;font-weight:500;
  background:rgba(79,142,247,.12);color:var(--accent);border:1px solid rgba(79,142,247,.2)}
.status-ok{color:var(--green)}
.status-err{color:var(--red)}

/* RATE LIMIT BAR */
.rate-wrap{margin-top:1rem}
.rate-label{display:flex;justify-content:space-between;font-size:.8rem;margin-bottom:.4rem}
.rate-track{height:8px;background:var(--border);border-radius:4px;overflow:hidden}
.rate-fill{height:100%;border-radius:4px;transition:width .8s ease}
.rate-fill.low{background:var(--green)}
.rate-fill.mid{background:var(--yellow)}
.rate-fill.high{background:var(--red)}

/* CHAT WIDGET */
.chat-section{background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:1.5rem;margin-bottom:2rem}
.chat-messages{height:200px;overflow-y:auto;margin-bottom:1rem;display:flex;flex-direction:column;gap:.5rem}
.msg{max-width:80%;padding:.6rem 1rem;border-radius:12px;font-size:.85rem;line-height:1.5}
.msg.user{align-self:flex-end;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.msg.ai{align-self:flex-start;background:var(--surface);border:1px solid var(--border)}
.chat-input-row{display:flex;gap:.75rem}
.chat-input{flex:1;background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:.7rem 1rem;color:var(--text);font-size:.9rem;outline:none;transition:border-color .2s}
.chat-input:focus{border-color:var(--accent)}
.btn{padding:.7rem 1.5rem;border-radius:10px;border:none;cursor:pointer;font-size:.9rem;
  font-weight:600;transition:all .2s}
.btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff}
.btn-primary:hover{opacity:.85;transform:translateY(-1px)}
.model-sel{background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:.7rem 1rem;color:var(--text);font-size:.85rem;outline:none;cursor:pointer}

/* EMPTY STATE */
.empty{text-align:center;padding:2rem;color:var(--muted);font-size:.9rem}
.empty-icon{font-size:2rem;margin-bottom:.5rem}

/* GLOW */
.glow{box-shadow:0 0 30px rgba(79,142,247,.08)}
</style>
</head>
<body>
<nav>
  <div class="logo">
    <div class="logo-icon"></div>
    NeuralMesh
  </div>
  <div class="nav-right">
    <span class="tier-badge" id="tierBadge">free</span>
    <span class="api-key-display" id="keyDisplay"></span>
  </div>
</nav>

<div class="container">
  <h1>AI Usage Dashboard</h1>
  <p class="subtitle" id="greeting">Loading your usage stats</p>

  <!-- STATS GRID -->
  <div class="stats-grid">
    <div class="stat-card blue glow">
      <div class="stat-icon"></div>
      <div class="stat-label">Total Tokens</div>
      <div class="stat-value" id="statTokens"></div>
      <div class="stat-sub">Across all models</div>
    </div>
    <div class="stat-card purple glow">
      <div class="stat-icon"></div>
      <div class="stat-label">API Requests</div>
      <div class="stat-value" id="statRequests"></div>
      <div class="stat-sub">Total lifetime</div>
    </div>
    <div class="stat-card green glow">
      <div class="stat-icon"></div>
      <div class="stat-label">Total Cost</div>
      <div class="stat-value" id="statCost"></div>
      <div class="stat-sub">USD billed</div>
    </div>
    <div class="stat-card yellow glow">
      <div class="stat-icon"></div>
      <div class="stat-label">Rate Limit</div>
      <div class="stat-value" id="statRate"></div>
      <div class="stat-sub">Requests / min</div>
    </div>
  </div>

  <!-- QUICK CHAT -->
  <div class="chat-section">
    <div class="panel-title"><span class="dot"></span> Quick Chat</div>
    <div class="chat-messages" id="chatMessages">
      <div class="msg ai"> Welcome to NeuralMesh. Select a model and start chatting!</div>
    </div>
    <div class="chat-input-row">
      <select class="model-sel" id="modelSel">
        <option value="chat"> chat (llama-3.1-8b)</option>
        <option value="code"> code (qwen  deepseek  claude)</option>
        <option value="creative"> creative (llama  claude)</option>
        <option value="reasoning"> reasoning (llama  deepseek  claude)</option>
        <option value="math"> math (qwen  deepseek  gemini)</option>
        <option value="factual"> factual (llama  gemini)</option>
      </select>
      <input class="chat-input" id="chatInput" placeholder="Ask anything" />
      <button class="btn btn-primary" onclick="sendChat()">Send </button>
    </div>
  </div>

  <!-- MODEL BREAKDOWN + HISTORY -->
  <div class="two-col">
    <div class="panel">
      <div class="panel-title"><span class="dot" style="background:var(--accent2)"></span> Model Usage</div>
      <div id="modelBars"><div class="empty"><div class="empty-icon"></div>No requests yet</div></div>
      <div class="rate-wrap">
        <div class="rate-label">
          <span style="font-size:.8rem;color:var(--muted)">Rate limit this minute</span>
          <span id="rateText" style="font-size:.8rem;color:var(--muted)">0 / 60</span>
        </div>
        <div class="rate-track"><div class="rate-fill low" id="rateFill" style="width:0%"></div></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title"><span class="dot" style="background:var(--green)"></span> Recent Requests</div>
      <div id="historyWrap">
        <div class="empty"><div class="empty-icon"></div>No history yet</div>
      </div>
    </div>
  </div>
</div>

<script>
const apiKey = new URLSearchParams(location.search).get('key') || '';

async function loadStats() {
  if (!apiKey) {
    document.getElementById('greeting').textContent = 'Add ?key=YOUR_API_KEY to the URL to see your stats';
    return;
  }
  try {
    const r = await fetch('/user/stats', {headers:{'X-Api-Key': apiKey}});
    const d = await r.json();
    if (d.error) { document.getElementById('greeting').textContent = d.error; return; }

    document.getElementById('greeting').textContent = `Welcome back! Last updated just now.`;
    document.getElementById('tierBadge').textContent = d.tier || 'free';
    document.getElementById('keyDisplay').textContent = apiKey.slice(0,6) + '';
    document.getElementById('statTokens').textContent = (d.total_tokens||0).toLocaleString();
    document.getElementById('statRequests').textContent = (d.total_requests||0).toLocaleString();
    document.getElementById('statCost').textContent = '$'+(d.total_cost_usd||0).toFixed(4);
    document.getElementById('statRate').textContent = (d.rate_limit||60);

    // Rate bar
    const used = d.rate_count_this_minute || 0;
    const limit = d.rate_limit || 60;
    const pct = Math.min(100, (used/limit)*100);
    document.getElementById('rateText').textContent = `${used} / ${limit}`;
    const fill = document.getElementById('rateFill');
    fill.style.width = pct + '%';
    fill.className = 'rate-fill ' + (pct < 50 ? 'low' : pct < 80 ? 'mid' : 'high');

    // Model bars
    const mb = d.model_breakdown || {};
    const keys = Object.keys(mb);
    if (keys.length) {
      const maxVal = Math.max(...Object.values(mb));
      document.getElementById('modelBars').innerHTML = keys.map(k =>
        `<div class="model-bar">
          <div class="model-bar-label"><span class="model-bar-name">${k}</span><span class="model-bar-count">${mb[k]}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${(mb[k]/maxVal*100).toFixed(1)}%"></div></div>
        </div>`
      ).join('') + document.getElementById('modelBars').innerHTML.includes('rate-wrap') ? '' : '';
    }

    // History
    const hist = d.recent_history || [];
    if (hist.length) {
      document.getElementById('historyWrap').innerHTML =
        `<table class="history-table">
          <thead><tr><th>Model</th><th>Tokens</th><th>Latency</th><th>Status</th></tr></thead>
          <tbody>${hist.map(h =>
            `<tr>
              <td><span class="model-tag">${h.model||''}</span></td>
              <td>${(h.tokens||0).toLocaleString()}</td>
              <td>${h.latency_ms ? h.latency_ms+'ms' : ''}</td>
              <td class="${h.status==='ok'?'status-ok':'status-err'}">${h.status||''}</td>
            </tr>`
          ).join('')}</tbody>
        </table>`;
    }
  } catch(e) {
    document.getElementById('greeting').textContent = 'Error loading stats. Check your API key.';
  }
}

function addMsg(role, text) {
  const wrap = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.textContent = text;
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const model = document.getElementById('modelSel').value;
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMsg('user', text);
  addMsg('ai', ' Thinking');
  try {
    const r = await fetch('/infer', {
      method:'POST',
      headers:{'Content-Type':'application/json','X-Api-Key':apiKey},
      body: JSON.stringify({prompt:text, task_type:model})
    });
    const d = await r.json();
    const msgs = document.getElementById('chatMessages');
    msgs.lastChild.textContent = d.response || d.detail || 'Error';
    loadStats();
  } catch(e) {
    document.getElementById('chatMessages').lastChild.textContent = 'Error connecting to API.';
  }
}

document.getElementById('chatInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

loadStats();
setInterval(loadStats, 30000);
</script>
</body>
</html>"""


@router.get("/user/dashboard", response_class=HTMLResponse)
async def user_dashboard_ui():
    """Serve the AI user dashboard HTML."""
    return HTMLResponse(content=_HTML)


@router.get("/user/stats")
async def user_stats_api(x_api_key: Optional[str] = Header(None)):
    """Return JSON stats for the authenticated user."""
    redis = get_redis_client()
    if not x_api_key:
        return JSONResponse({"error": "Missing X-Api-Key header"}, status_code=401)
    try:
        key_record = verify_api_key(x_api_key, redis)
    except Exception:
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    stats = await get_user_stats(key_record.hash, redis)
    tier_info = await get_user_tier_info(key_record.hash, redis)
    return {**stats, **tier_info}
