"""GPU Provider Dashboard  earnings tracker with cashout flow."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Header
from fastapi.responses import HTMLResponse, JSONResponse

from app.stages.cache import get_redis_client
from app.lib.dashboard_data import get_provider_dashboard, get_network_stats

router = APIRouter(tags=["gpu-dashboard"])

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NeuralMesh  GPU Provider Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#060910;--surface:#0a0f1a;--card:#0f1623;--border:#1a2840;
  --accent:#00d4aa;--accent2:#0ea5e9;--purple:#8b5cf6;
  --green:#10b981;--yellow:#f59e0b;--red:#ef4444;--orange:#f97316;
  --text:#e2e8f0;--muted:#475569;--font:'Inter',system-ui,sans-serif
}
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* NAV */
nav{display:flex;align-items:center;justify-content:space-between;padding:1rem 2rem;
  border-bottom:1px solid var(--border);background:rgba(10,15,26,0.9);backdrop-filter:blur(16px);
  position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:.75rem;font-weight:700;font-size:1.1rem}
.logo-icon{width:36px;height:36px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.1rem}
.node-id{font-family:monospace;font-size:.72rem;color:var(--muted);
  background:var(--card);padding:.2rem .6rem;border-radius:5px;border:1px solid var(--border)}
.status-pill{display:flex;align-items:center;gap:.4rem;padding:.25rem .75rem;border-radius:999px;
  font-size:.75rem;font-weight:600;background:rgba(16,185,129,.12);color:var(--green);
  border:1px solid rgba(16,185,129,.2)}
.status-dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* HERO EARNINGS */
.hero{background:linear-gradient(135deg,rgba(0,212,170,.08),rgba(14,165,233,.08));
  border:1px solid rgba(0,212,170,.15);border-radius:20px;padding:2rem;margin-bottom:1.5rem;
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem}
.hero-left h2{font-size:2.5rem;font-weight:800;
  background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;
  -webkit-text-fill-color:transparent;background-clip:text}
.hero-left p{color:var(--muted);font-size:.85rem;margin-top:.25rem}
.hero-right{display:flex;gap:1rem;flex-wrap:wrap}
.hero-stat{text-align:center;background:rgba(255,255,255,.03);border:1px solid var(--border);
  border-radius:12px;padding:.75rem 1.25rem}
.hero-stat-val{font-size:1.25rem;font-weight:700;color:var(--text)}
.hero-stat-lbl{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:.15rem}

/* LAYOUT */
.container{max-width:1200px;margin:0 auto;padding:1.5rem 2rem}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.5rem}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.5rem}
@media(max-width:768px){.grid2{grid-template-columns:1fr}}

/* STAT CARDS */
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.5rem;
  transition:transform .2s,border-color .2s;position:relative;overflow:hidden}
.card:hover{transform:translateY(-2px)}
.card-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:.75rem}
.card-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;
  justify-content:center;font-size:1.1rem}
.card-icon.teal{background:rgba(0,212,170,.12);border:1px solid rgba(0,212,170,.2)}
.card-icon.blue{background:rgba(14,165,233,.12);border:1px solid rgba(14,165,233,.2)}
.card-icon.purple{background:rgba(139,92,246,.12);border:1px solid rgba(139,92,246,.2)}
.card-icon.orange{background:rgba(249,115,22,.12);border:1px solid rgba(249,115,22,.2)}
.trend{font-size:.72rem;font-weight:500;padding:.15rem .4rem;border-radius:4px}
.trend.up{color:var(--green);background:rgba(16,185,129,.1)}
.trend.down{color:var(--red);background:rgba(239,68,68,.1)}
.card-label{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.25rem}
.card-value{font-size:1.75rem;font-weight:700}
.card-sub{font-size:.75rem;color:var(--muted);margin-top:.2rem}
.card::after{content:'';position:absolute;bottom:0;left:0;right:0;height:2px}
.card.teal-b::after{background:linear-gradient(90deg,var(--accent),transparent)}
.card.blue-b::after{background:linear-gradient(90deg,var(--accent2),transparent)}
.card.purple-b::after{background:linear-gradient(90deg,var(--purple),transparent)}
.card.orange-b::after{background:linear-gradient(90deg,var(--orange),transparent)}

/* PANELS */
.panel{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.5rem}
.panel-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.25rem}
.panel-title{font-size:.95rem;font-weight:600;display:flex;align-items:center;gap:.5rem}
.panel-badge{padding:.2rem .6rem;border-radius:6px;font-size:.7rem;font-weight:600;
  background:rgba(0,212,170,.1);color:var(--accent);border:1px solid rgba(0,212,170,.2)}

/* EARNINGS CHART (CSS bars) */
.earnings-chart{display:flex;align-items:flex-end;gap:.4rem;height:100px;margin-bottom:1rem}
.bar-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:.25rem}
.bar-body{width:100%;border-radius:4px 4px 0 0;background:linear-gradient(to top,var(--accent2),var(--accent);transition:height .8s ease;min-height:4px}
.bar-day{font-size:.6rem;color:var(--muted)}

/* CASHOUT FORM */
.form-group{margin-bottom:1rem}
.form-label{display:block;font-size:.78rem;color:var(--muted);margin-bottom:.4rem;font-weight:500;
  text-transform:uppercase;letter-spacing:.05em}
.form-input{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:.7rem 1rem;color:var(--text);font-size:.9rem;outline:none;transition:border-color .2s}
.form-input:focus{border-color:var(--accent)}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
.btn{padding:.75rem 1.5rem;border-radius:10px;border:none;cursor:pointer;font-size:.9rem;font-weight:600;
  transition:all .2s;width:100%;margin-top:.5rem}
.btn-cashout{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#000;font-weight:700}
.btn-cashout:hover{opacity:.85;transform:translateY(-1px)}
.btn-cashout:disabled{opacity:.4;cursor:not-allowed;transform:none}
.threshold-note{font-size:.75rem;color:var(--muted);margin-top:.5rem;text-align:center}
.threshold-note span{color:var(--yellow)}

/* PAYOUT TABLE */
.payout-table{width:100%;border-collapse:collapse;font-size:.82rem}
.payout-table th{color:var(--muted);font-weight:500;text-align:left;padding:.5rem .75rem;
  border-bottom:1px solid var(--border);font-size:.7rem;text-transform:uppercase;letter-spacing:.06em}
.payout-table td{padding:.65rem .75rem;border-bottom:1px solid rgba(26,40,64,.6)}
.payout-table tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:4px;font-size:.7rem;font-weight:500}
.badge-pending{background:rgba(245,158,11,.1);color:var(--yellow);border:1px solid rgba(245,158,11,.2)}
.badge-approved{background:rgba(16,185,129,.1);color:var(--green);border:1px solid rgba(16,185,129,.2)}
.badge-rejected{background:rgba(239,68,68,.1);color:var(--red);border:1px solid rgba(239,68,68,.2)}

/* NETWORK STRIP */
.network-strip{display:flex;gap:1rem;margin-bottom:1.5rem;flex-wrap:wrap}
.net-item{flex:1;min-width:150px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:1rem;text-align:center}
.net-val{font-size:1.3rem;font-weight:700;color:var(--accent)}
.net-lbl{font-size:.7rem;color:var(--muted);margin-top:.2rem;text-transform:uppercase;letter-spacing:.06em}

/* ALERT */
.alert{padding:.75rem 1rem;border-radius:10px;font-size:.82rem;margin-bottom:1rem;display:none}
.alert-success{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.2);color:var(--green)}
.alert-error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);color:var(--red)}
</style>
</head>
<body>
<nav>
  <div class="logo">
    <div class="logo-icon"></div>
    NeuralMesh Provider
  </div>
  <div style="display:flex;align-items:center;gap:.75rem">
    <span class="node-id" id="nodeIdDisplay">node-</span>
    <span class="status-pill"><span class="status-dot"></span>Online</span>
  </div>
</nav>

<div class="container">

  <!-- HERO -->
  <div class="hero">
    <div class="hero-left">
      <h2 id="heroEarned">$0.0000</h2>
      <p>Total earnings since joining NeuralMesh</p>
    </div>
    <div class="hero-right">
      <div class="hero-stat">
        <div class="hero-stat-val" id="heroPending">$0.00</div>
        <div class="hero-stat-lbl">Pending Payout</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-val" id="heroPaidOut">$0.00</div>
        <div class="hero-stat-lbl">Paid Out</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-val" id="heroTokens">0</div>
        <div class="hero-stat-lbl">Tokens Served</div>
      </div>
    </div>
  </div>

  <!-- NETWORK STRIP -->
  <div class="network-strip">
    <div class="net-item"><div class="net-val" id="netNodes"></div><div class="net-lbl">Active Nodes</div></div>
    <div class="net-item"><div class="net-val" id="netUptime">99.7%</div><div class="net-lbl">Network Uptime</div></div>
    <div class="net-item"><div class="net-val">$0.0001</div><div class="net-lbl">Rate/1k tokens (local)</div></div>
    <div class="net-item"><div class="net-val">$0.0005</div><div class="net-lbl">Rate/1k tokens (cloud)</div></div>
  </div>

  <!-- STAT CARDS -->
  <div class="grid3">
    <div class="card teal-b">
      <div class="card-top">
        <div class="card-icon teal"></div>
        <span class="trend up">+12%</span>
      </div>
      <div class="card-label">Available to Withdraw</div>
      <div class="card-value" id="cardPending">$0.0000</div>
      <div class="card-sub">Min. $1.00 threshold</div>
    </div>
    <div class="card blue-b">
      <div class="card-top">
        <div class="card-icon blue"></div>
        <span class="trend up">+8%</span>
      </div>
      <div class="card-label">Tokens This Week</div>
      <div class="card-value" id="cardTokens">0</div>
      <div class="card-sub">Across all task types</div>
    </div>
    <div class="card orange-b">
      <div class="card-top">
        <div class="card-icon orange"></div>
      </div>
      <div class="card-label">Paid Out Total</div>
      <div class="card-value" id="cardPaid">$0.00</div>
      <div class="card-sub">Via USD bank transfer</div>
    </div>
  </div>

  <!-- CASHOUT + HISTORY -->
  <div class="grid2">
    <!-- CASHOUT FORM -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title"> Request Payout</div>
        <span class="panel-badge">USD Bank Transfer</span>
      </div>

      <div id="alertBox" class="alert"></div>

      <div class="form-group">
        <label class="form-label">Node ID</label>
        <input class="form-input" id="nodeInput" placeholder="node-xxxx-xxxx" />
      </div>
      <div class="form-group">
        <label class="form-label">Stripe Connected Account ID</label>
        <input class="form-input" id="acctInput" placeholder="acct_xxxxxxxxxxxx" />
      </div>
      <div class="form-group">
        <label class="form-label">Amount (USD)</label>
        <input class="form-input" type="number" id="amountInput" placeholder="1.00" step="0.01" min="1.00" />
      </div>
      <div class="form-group">
        <label class="form-label">Bank / Payment Reference</label>
        <input class="form-input" id="referenceInput" placeholder="e.g. Chase checking 4521" />
      </div>
      <button class="btn btn-cashout" onclick="submitPayout()"> Request Payout</button>
      <p class="threshold-note">Minimum payout: <span>$1.00 USD</span>  Sent via Stripe bank transfer</p>
    </div>

    <!-- PAYOUT HISTORY -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title"> Payout History</div>
      </div>
      <div id="payoutHistory">
        <table class="payout-table">
          <thead><tr><th>Date</th><th>Amount</th><th>Status</th><th>Ref</th></tr></thead>
          <tbody id="payoutRows"><tr><td colspan="4" style="text-align:center;color:var(--muted);padding:1.5rem">No payouts yet</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

</div>

<script>
const nodeId = new URLSearchParams(location.search).get('node') || '';

async function loadDashboard() {
  if (!nodeId) {
    document.getElementById('heroEarned').textContent = 'Add ?node=YOUR_NODE_ID';
    return;
  }
  document.getElementById('nodeIdDisplay').textContent = 'node-' + nodeId.slice(0,8);
  document.getElementById('nodeInput').value = nodeId;

  try {
    const r = await fetch(`/gpu/stats/${nodeId}`);
    const d = await r.json();

    document.getElementById('heroEarned').textContent = '$' + (d.total_earned_usd||0).toFixed(4);
    document.getElementById('heroPending').textContent = '$' + (d.pending_payout_usd||0).toFixed(4);
    document.getElementById('heroPaidOut').textContent = '$' + (d.paid_out_usd||0).toFixed(4);
    document.getElementById('heroTokens').textContent = (d.token_count||0).toLocaleString();
    document.getElementById('cardPending').textContent = '$' + (d.pending_payout_usd||0).toFixed(4);
    document.getElementById('cardTokens').textContent = (d.token_count||0).toLocaleString();
    document.getElementById('cardPaid').textContent = '$' + (d.paid_out_usd||0).toFixed(4);

    const payouts = d.payout_requests || [];
    if (payouts.length) {
      document.getElementById('payoutRows').innerHTML = payouts.map(p => {
        const date = p.created_at ? new Date(p.created_at*1000).toLocaleDateString() : '';
        const statusClass = p.status==='approved'?'badge-approved':p.status==='rejected'?'badge-rejected':'badge-pending';
        return `<tr>
          <td>${date}</td>
          <td>$${(p.amount_usd||0).toFixed(2)}</td>
          <td><span class="badge ${statusClass}">${p.status||'pending'}</span></td>
          <td style="color:var(--muted);font-size:.75rem">${(p.bank_ref||'').slice(0,20)}</td>
        </tr>`;
      }).join('');
    }
  } catch(e) {}

  try {
    const rn = await fetch('/gpu/network');
    const nd = await rn.json();
    document.getElementById('netNodes').textContent = nd.active_nodes || '';
    document.getElementById('netUptime').textContent = nd.uptime_pct + '%';
  } catch(e) {}
}

function showAlert(msg, type) {
  const box = document.getElementById('alertBox');
  box.textContent = msg;
  box.className = 'alert alert-' + type;
  box.style.display = 'block';
  setTimeout(() => { box.style.display = 'none'; }, 5000);
}

async function submitPayout() {
  const nid = document.getElementById('nodeInput').value.trim();
  const acct = document.getElementById('acctInput').value.trim();
  const amount = parseFloat(document.getElementById('amountInput').value);
  const ref = document.getElementById('referenceInput').value.trim();

  if (!nid || !acct || !amount || amount < 1.0) {
    showAlert('Please fill all fields. Minimum payout is $1.00.', 'error');
    return;
  }

  try {
    const r = await fetch('/provider/payout', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({node_id:nid, stripe_account_id:acct, amount_usd:amount, bank_ref:ref})
    });
    const d = await r.json();
    if (r.ok) {
      showAlert(' Payout request submitted! Admin will review within 1-2 business days.', 'success');
      loadDashboard();
    } else {
      showAlert(d.detail || 'Error submitting payout request.', 'error');
    }
  } catch(e) {
    showAlert('Network error. Please try again.', 'error');
  }
}

loadDashboard();
setInterval(loadDashboard, 60000);
</script>
</body>
</html>"""


@router.get("/gpu/dashboard", response_class=HTMLResponse)
async def gpu_dashboard_ui():
    """Serve the GPU provider dashboard HTML."""
    return HTMLResponse(content=_HTML)


@router.get("/gpu/stats/{node_id}")
async def gpu_stats_api(node_id: str):
    """Return JSON earnings stats for a GPU provider node."""
    redis = get_redis_client()
    data = await get_provider_dashboard(node_id, redis)
    return data


@router.get("/gpu/network")
async def gpu_network_api():
    """Return global network stats."""
    redis = get_redis_client()
    return await get_network_stats(redis)
