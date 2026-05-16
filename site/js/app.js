const API_URL = '';

async function api(path, opts = {}) {
  const token = localStorage.getItem('token');
  const headers = { 'Content-Type': 'application/json', ...opts.headers };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const r = await fetch(API_URL + path, { ...opts, headers });
  const d = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data: d };
}

async function handleLogin(e) {
  e.preventDefault();
  const msg = document.getElementById('login-msg');
  msg.className = 'msg';
  msg.textContent = '';

  const username = document.getElementById('login-user').value.trim();
  const pin = document.getElementById('login-pin').value.trim();
  if (!username || !pin) { showMsg('login-msg', 'Preencha todos os campos.', 'error'); return; }

  const btn = e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  btn.textContent = 'Entrando...';

  const { ok, data } = await api('/api/login', {
    method: 'POST',
    body: JSON.stringify({ username, pin, appVersion: '99.99.99', web_login: true })
  });

  btn.disabled = false;
  btn.textContent = 'Entrar';

  if (ok) {
    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    window.location.href = '/profile';
  } else {
    showMsg('login-msg', data.error || 'Erro ao entrar.', 'error');
  }
}

async function loadProfile() {
  const token = localStorage.getItem('token');
  if (!token) { window.location.href = '/login'; return; }

  const { ok, data } = await api('/api/me');
  if (!ok) {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/login';
    return;
  }

  document.getElementById('pv-username').textContent = data.username || '—';
  const un2 = document.getElementById('pv-username2');
  if (un2) un2.textContent = data.username || '—';
  document.getElementById('pv-discord').textContent = data.discord_id || 'Não vinculado';
  document.getElementById('pv-phone').textContent = data.phone || '—';
  document.getElementById('pv-avatar').src = data.avatar_url || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"%3E%3Crect fill="%233b82f6" width="100" height="100"/%3E%3Ctext x="50" y="58" text-anchor="middle" fill="%23fff" font-size="40" font-weight="700" font-family="sans-serif"%3E' + (data.username ? data.username[0].toUpperCase() : '?') + '%3C/text%3E%3C/svg%3E';

  const stored = JSON.parse(localStorage.getItem('user') || '{}');
  const plan = data.plan || stored.plan || 'free';
  const planEl = document.getElementById('pv-plan');
  const planEl2 = document.getElementById('pv-plan2');
  const planText = plan === 'premium' ? 'Premium' : 'Grátis';
  const planColor = plan === 'premium' ? '#10b981' : 'var(--muted)';
  planEl.textContent = planText;
  planEl.style.color = planColor;
  if (planEl2) { planEl2.textContent = planText; planEl2.style.color = planColor; }

  const kmEl = document.getElementById('pv-total-km');
  if (kmEl) {
    const km = data.total_km || 0;
    kmEl.textContent = km.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' km';
  }

  const empresaSection = document.getElementById('empresa-section');
  if (empresaSection) {
    empresaSection.style.display = data.is_company_owner ? '' : 'none';
  }
}

function handleLogout() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  window.location.href = '/login';
}

async function resetHwid() {
  if (!confirm('Tem certeza que deseja resetar seu HWID?\n\nVocê só pode fazer isso 1 vez a cada 30 dias.')) return;
  const btn = document.getElementById('reset-hwid-btn');
  const msg = document.getElementById('reset-hwid-msg');
  btn.disabled = true;
  btn.textContent = 'Resetando...';
  msg.textContent = '';
  const { ok, data } = await api('/api/reset-hwid', { method: 'POST' });
  btn.disabled = false;
  btn.textContent = 'Resetar HWID';
  if (ok) {
    msg.innerHTML = '<span style="color:#10b981;">✓ HWID resetado com sucesso!</span>';
  } else {
    msg.textContent = data.error || 'Erro ao resetar. Tente mais tarde.';
    msg.style.color = '#f87171';
  }
  setTimeout(() => { msg.textContent = ''; msg.style.color = ''; }, 5000);
}

document.addEventListener('DOMContentLoaded', () => {
  const loginForm = document.getElementById('login-form');
  if (loginForm) loginForm.addEventListener('submit', handleLogin);

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.addEventListener('click', handleLogout);

  const profilePage = document.getElementById('profile-page');
  if (profilePage) {
    loadProfile();
    const resetBtn = document.getElementById('reset-hwid-btn');
    if (resetBtn) resetBtn.addEventListener('click', resetHwid);
  }
});

function showMsg(id, text, type) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = 'msg show ' + type;
}
