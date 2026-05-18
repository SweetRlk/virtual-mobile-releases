const API_URL = '';
let _turnstileWidgetId = null;
let _challengeToken = '';

document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('register-form');
  const msg = document.getElementById('msg');
  const estadoSelect = document.getElementById('estado');

  // Busca challenge token e config
  fetch(API_URL + '/api/challenge').then(r => r.json()).then(d => {
    _challengeToken = d.challenge || '';
  }).catch(() => {});

  // Carrega config e init Turnstile se habilitado
  fetch(API_URL + '/api/public-config').then(r => r.json()).then(cfg => {
    if (cfg.captcha_enabled && cfg.turnstile_site_key) {
      window._onTurnstileReady = () => {
        _turnstileWidgetId = turnstile.render('#captcha-container', {
          sitekey: cfg.turnstile_site_key,
          theme: 'dark'
        });
      };
      const script = document.createElement('script');
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=_onTurnstileReady';
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }
  }).catch(() => {});

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    msg.className = 'msg';
    msg.textContent = '';

    const username = document.getElementById('username').value.trim();
    const pin = document.getElementById('pin').value.trim();
    const pinConfirm = document.getElementById('pin-confirm').value.trim();
    const discord_id = document.getElementById('discord').value.trim();
    const estado = estadoSelect.value;

    if (!username || !pin || !pinConfirm) {
      showMsg('Preencha todos os campos obrigatórios.', 'error');
      return;
    }
    if (!discord_id) {
      showMsg('Informe seu Discord ID.', 'error');
      return;
    }
    if (/\d/.test(username)) { showMsg('O usuário não pode conter números.', 'error'); return; }
    if (!/^\d{17,20}$/.test(discord_id)) {
      showMsg('Discord ID inválido. Deve conter apenas números (17-20 dígitos).', 'error');
      return;
    }
    if (pin !== pinConfirm) {
      showMsg('Os PINs não conferem.', 'error');
      return;
    }
    if (pin.length !== 4 || !/^\d{4}$/.test(pin)) {
      showMsg('O PIN deve ter exatamente 4 dígitos numéricos.', 'error');
      return;
    }
    if (username.length < 3 || username.length > 20) {
      showMsg('O usuário não pode conter números e deve ter entre 3 e 20 caracteres.', 'error');
      return;
    }

    // Captcha token (se não carregou, deixa passar — CSP do Cloudflare pode bloquear)
    let captcha_token = '';
    if (_turnstileWidgetId !== null) {
      try {
        if (typeof turnstile !== 'undefined') {
          captcha_token = turnstile.getResponse(_turnstileWidgetId) || '';
        }
      } catch(_) {}
    }

    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = 'Registrando...';

    try {
      const r = await fetch(API_URL + '/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, pin, discord_id, estado, captcha_token, challenge: _challengeToken })
      });
      const d = await r.json();
      if (r.ok) {
        showMsg('Conta criada com sucesso! <a href="/login" style="color:#3b82f6;text-decoration:underline;">Clique aqui para entrar</a>', 'success');
        form.reset();
        if (_turnstileWidgetId !== null) turnstile.reset(_turnstileWidgetId);
      } else {
        showMsg(d.error || 'Erro ao criar conta.', 'error');
        if (_turnstileWidgetId !== null) turnstile.reset(_turnstileWidgetId);
      }
    } catch (err) {
      showMsg('Erro de conexão com o servidor.', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Criar Conta';
    }
  });
});

function showMsg(text, type) {
  const el = document.getElementById('msg');
  el.innerHTML = text;
  el.className = 'msg show ' + type;
}
