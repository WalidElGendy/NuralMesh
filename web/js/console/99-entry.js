import { boot } from './70-app.js';

boot().catch((e) => {
  console.error('[mesh] boot failed', e);
  const app = document.getElementById('app');
  if (app) {
    app.innerHTML = `<div style="display:grid;place-items:center;height:100dvh;padding:24px;text-align:center;gap:8px">
      <strong>The console failed to start.</strong>
      <span style="color:var(--ink-3);font-size:13px;max-width:46ch">${String(e.message || e)}</span>
      <button class="newbtn" style="width:auto" onclick="location.reload()">Reload</button>
    </div>`;
  }
});
