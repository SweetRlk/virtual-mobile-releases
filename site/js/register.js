const API_URL = '';

const ESTADOS = [
  'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG',
  'PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'
];

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('register-form');
  const msg = document.getElementById('msg');
  const estadoSelect = document.getElementById('estado');

  ESTADOS.forEach(uf => {
    const opt = document.createElement('option');
    opt.value = uf;
    opt.textContent = uf;
    estadoSelect.appendChild(opt);
  });

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

    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = 'Registrando...';

    try {
      const r = await fetch(API_URL + '/api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, pin, discord_id, estado })
      });
      const d = await r.json();
      if (r.ok) {
        showMsg('Conta criada com sucesso! <a href="/login" style="color:#3b82f6;text-decoration:underline;">Clique aqui para entrar</a>', 'success');
        form.reset();
      } else {
        showMsg(d.error || 'Erro ao criar conta.', 'error');
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
