import sqlite3
import os
import bcrypt
import secrets
import urllib.request
import json as json_lib
import random
import time
from flask import Flask, request, jsonify, render_template_string, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=['app://*'])

DB_PATH = os.path.join(os.path.dirname(__file__), 'sweet.db')
ADMIN_KEY = os.environ.get('ADMIN_KEY', secrets.token_hex(16))

# ===== RATE LIMITING (in-memory) =====
SESSION_TTL = 86400  # Token expira em 24h
LOGIN_MAX_ATTEMPTS = 5  # Máximo de tentativas por IP
LOGIN_LOCKOUT_SECONDS = 300  # Bloqueio de 5 minutos após exceder tentativas
_login_attempts = {}  # { ip: { count: int, first_attempt: float, locked_until: float } }

def check_login_rate_limit(ip):
    """Returns (allowed: bool, retry_after: int). Blocks brute-force on login."""
    now = time.time()
    entry = _login_attempts.get(ip)
    if not entry:
        return True, 0
    # Locked out?
    if entry.get('locked_until', 0) > now:
        return False, int(entry['locked_until'] - now)
    # Window expired? Reset
    if now - entry['first_attempt'] > LOGIN_LOCKOUT_SECONDS:
        _login_attempts.pop(ip, None)
        return True, 0
    if entry['count'] >= LOGIN_MAX_ATTEMPTS:
        entry['locked_until'] = now + LOGIN_LOCKOUT_SECONDS
        return False, LOGIN_LOCKOUT_SECONDS
    return True, 0

def record_login_attempt(ip, success):
    now = time.time()
    if success:
        _login_attempts.pop(ip, None)
        return
    entry = _login_attempts.get(ip)
    if not entry or (now - entry['first_attempt'] > LOGIN_LOCKOUT_SECONDS):
        _login_attempts[ip] = {'count': 1, 'first_attempt': now, 'locked_until': 0}
    else:
        entry['count'] += 1

# Discord config (server-side only — never sent to client)
DISCORD_WEBHOOK_PEDAGIO = os.environ.get('DISCORD_WEBHOOK_PEDAGIO', 'https://discord.com/api/webhooks/1494199351998677123/JWYCkWfPXzC5us4O_IC_y7nmb9_LIiDsZX8AoQP0tJPx6kylvRWjUg2paHL037W7KHJt')
DISCORD_WEBHOOK_NOTA = os.environ.get('DISCORD_WEBHOOK_NOTA', 'https://discord.com/api/webhooks/1494560743255834674/BCIIlqyWd5tN2RZYSTleSFBO1nkAUSfnLfiNct95roAiSkS1-TGcRtkzKF9DsCQdtBOe')
DISCORD_EMBED_IMAGE = os.environ.get('DISCORD_EMBED_IMAGE', 'https://cdn.discordapp.com/attachments/1489372687817248939/1492754254329282771/tag-sem-parar-v1.png?ex=69dc7b3c&is=69db29bc&hm=8b36a59ed6d84286f9235e9134492b5036636b7ec247a04caf888a47023e0c67')

# DDD por estado brasileiro
DDD_POR_ESTADO = {
    'AC': [68], 'AL': [82], 'AP': [96], 'AM': [92, 97],
    'BA': [71, 73, 74, 75, 77], 'CE': [85, 88], 'DF': [61],
    'ES': [27, 28], 'GO': [62, 64], 'MA': [98, 99],
    'MT': [65, 66], 'MS': [67], 'MG': [31, 32, 33, 34, 35, 37, 38],
    'PA': [91, 93, 94], 'PB': [83], 'PR': [41, 42, 43, 44, 45, 46],
    'PE': [81, 87], 'PI': [86, 89], 'RJ': [21, 22, 24],
    'RN': [84], 'RS': [51, 53, 54, 55], 'RO': [69], 'RR': [95],
    'SC': [47, 48, 49], 'SP': [11, 12, 13, 14, 15, 16, 17, 18, 19],
    'SE': [79], 'TO': [63],
}

def gerar_telefone(estado):
    """Gera telefone brasileiro no formato (XX) 9XXXX-XXXX baseado no estado."""
    ddds = DDD_POR_ESTADO.get(estado.upper(), [11])
    ddd = random.choice(ddds)
    n1 = random.randint(1000, 9999)
    n2 = random.randint(1000, 9999)
    return f'({ddd:02d}) 9{n1}-{n2}'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pin_hash TEXT NOT NULL,
            discord_id TEXT DEFAULT '',
            hwid TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT DEFAULT '',
            from_user TEXT DEFAULT '',
            to_user TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    # Migration: add columns if missing
    cols = [row[1] for row in conn.execute('PRAGMA table_info(users)').fetchall()]
    if 'hwid' not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN hwid TEXT DEFAULT ''")
    if 'balance' not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0")
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (from_user_id) REFERENCES users(id),
            FOREIGN KEY (to_user_id) REFERENCES users(id)
        )
    ''')
    # Contacts table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            contact_user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (contact_user_id) REFERENCES users(id),
            UNIQUE(user_id, contact_user_id)
        )
    ''')
    # Groups table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS groups_ (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            avatar_url TEXT DEFAULT '',
            owner_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(id)
        )
    ''')
    # Group members
    conn.execute('''
        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES groups_(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(group_id, user_id)
        )
    ''')
    # Group messages
    conn.execute('''
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            from_user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES groups_(id),
            FOREIGN KEY (from_user_id) REFERENCES users(id)
        )
    ''')
    # Migration: avatar_url column on users
    if 'avatar_url' not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT DEFAULT ''")
    if 'phone' not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    if 'estado' not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN estado TEXT DEFAULT ''")
    # User data store (notas, config, etc.)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_data (
            user_id INTEGER NOT NULL,
            data_key TEXT NOT NULL,
            data_value TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, data_key),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()


# ===== HELPERS =====

def verify_token(token):
    """Verify session token and return user row or None. Enforces token expiration."""
    if not token:
        return None
    conn = get_db()
    row = conn.execute('''
        SELECT u.id, u.username, u.discord_id, u.avatar_url, u.phone, s.created_at as session_created
        FROM sessions s JOIN users u ON s.user_id = u.id
        WHERE s.token = ?
    ''', (token,)).fetchone()
    if row:
        # Check token expiration
        import datetime
        created = datetime.datetime.strptime(row['session_created'], '%Y-%m-%d %H:%M:%S') if isinstance(row['session_created'], str) else row['session_created']
        age = (datetime.datetime.utcnow() - created).total_seconds()
        if age > SESSION_TTL:
            conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
            conn.commit()
            conn.close()
            return None
    conn.close()
    return row


def validate_and_create_user(data):
    """Validate user input and create user. Returns (dict, status_code)."""
    username = (data.get('username') or '').strip()
    pin = (data.get('pin') or '').strip()

    if not username or not pin:
        return {'error': 'Usu\u00e1rio e PIN s\u00e3o obrigat\u00f3rios'}, 400
    if len(pin) < 4 or len(pin) > 8 or not pin.isdigit():
        return {'error': 'PIN deve ter 4-8 d\u00edgitos num\u00e9ricos'}, 400
    if len(username) < 3 or len(username) > 20:
        return {'error': 'Usu\u00e1rio deve ter entre 3 e 20 caracteres'}, 400

    pin_hash = bcrypt.hashpw(pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    discord_id = (data.get('discord_id') or '').strip()
    estado = (data.get('estado') or '').strip().upper()

    phone = ''
    if estado and estado in DDD_POR_ESTADO:
        phone = gerar_telefone(estado)

    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (username, pin_hash, discord_id, estado, phone) VALUES (?, ?, ?, ?, ?)',
            (username, pin_hash, discord_id, estado, phone)
        )
        conn.commit()
        return {'success': True, 'message': f'Usu\u00e1rio {username} criado', 'phone': phone, 'estado': estado}, 201
    except sqlite3.IntegrityError:
        return {'error': 'Usu\u00e1rio j\u00e1 existe'}, 409
    finally:
        conn.close()


# ===== AUTH =====

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    username = (data.get('username') or '').strip()
    pin = (data.get('pin') or '').strip()

    if not username or not pin:
        return jsonify({'error': 'Usuário e PIN são obrigatórios'}), 400

    if len(pin) < 4 or len(pin) > 8:
        return jsonify({'error': 'PIN deve ter entre 4 e 8 dígitos'}), 400

    if not pin.isdigit():
        return jsonify({'error': 'PIN deve conter apenas números'}), 400

    if len(username) < 3 or len(username) > 20:
        return jsonify({'error': 'Usuário deve ter entre 3 e 20 caracteres'}), 400

    pin_hash = bcrypt.hashpw(pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    discord_id = (data.get('discord_id') or '').strip()
    estado = (data.get('estado') or '').strip().upper()

    phone = ''
    if estado and estado in DDD_POR_ESTADO:
        phone = gerar_telefone(estado)

    conn = get_db()
    try:
        conn.execute(
            'INSERT INTO users (username, pin_hash, discord_id, estado, phone) VALUES (?, ?, ?, ?, ?)',
            (username, pin_hash, discord_id, estado, phone)
        )
        conn.commit()
        return jsonify({'success': True, 'message': f'Usuário {username} criado'}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Usuário já existe'}), 409
    finally:
        conn.close()


@app.route('/api/login', methods=['POST'])
def login():
    # Rate limiting
    client_ip = request.remote_addr
    allowed, retry_after = check_login_rate_limit(client_ip)
    if not allowed:
        resp = jsonify({'error': f'Muitas tentativas. Tente novamente em {retry_after}s.'})
        resp.headers['Retry-After'] = str(retry_after)
        return resp, 429

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    username = (data.get('username') or '').strip()
    pin = (data.get('pin') or '').strip()

    if not username or not pin:
        return jsonify({'error': 'Usuário e PIN são obrigatórios'}), 400

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

    if not user:
        conn.close()
        record_login_attempt(client_ip, False)
        return jsonify({'error': 'Usuário ou PIN incorreto'}), 401

    if not bcrypt.checkpw(pin.encode('utf-8'), user['pin_hash'].encode('utf-8')):
        conn.close()
        record_login_attempt(client_ip, False)
        return jsonify({'error': 'Usuário ou PIN incorreto'}), 401

    # HWID validation
    hwid = (data.get('hwid') or '').strip()
    stored_hwid = user['hwid'] or ''
    if stored_hwid and not hwid:
        conn.close()
        return jsonify({'error': 'Identificação do dispositivo é obrigatória.'}), 403
    if hwid:
        if stored_hwid and stored_hwid != hwid:
            conn.close()
            return jsonify({'error': 'Esta conta já está vinculada a outro dispositivo. Contate o administrador.'}), 403
        if not stored_hwid:
            conn.execute('UPDATE users SET hwid = ? WHERE id = ?', (hwid, user['id']))

    # Single session: invalidate all previous sessions for this user
    conn.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))

    token = secrets.token_hex(32)
    conn.execute('INSERT INTO sessions (token, user_id) VALUES (?, ?)', (token, user['id']))
    conn.commit()
    conn.close()

    record_login_attempt(client_ip, True)

    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'discord_id': user['discord_id'],
            'avatar_url': user['avatar_url'] or '',
            'phone': user['phone'] or '',
        }
    })


@app.route('/api/me', methods=['GET'])
def me():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return jsonify({'error': 'Token não fornecido'}), 401

    conn = get_db()
    row = conn.execute('''
        SELECT u.id, u.username, u.discord_id, u.avatar_url, u.phone
        FROM sessions s JOIN users u ON s.user_id = u.id
        WHERE s.token = ?
    ''', (token,)).fetchone()
    conn.close()

    if not row:
        return jsonify({'error': 'Sessão inválida'}), 401

    return jsonify({
        'id': row['id'],
        'username': row['username'],
        'discord_id': row['discord_id'],
        'avatar_url': row['avatar_url'] or '',
        'phone': row['phone'] or '',
    })


@app.route('/api/logout', methods=['POST'])
def logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if token:
        conn = get_db()
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
        conn.close()
    return jsonify({'success': True})


# ===== HEALTH =====

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


# ===== ADMIN PANEL =====

ADMIN_HTML = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sweet Admin</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0a0a0f; color: #e0e0e0; font-family: -apple-system, 'Segoe UI', sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; }
  h1 { font-size: 22px; margin-bottom: 20px; color: #00ff88; }
  h2 { font-size: 16px; margin: 20px 0 10px; opacity: 0.6; }
  .card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 16px; margin-bottom: 12px; }
  .form-row { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  input, button, select { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 10px 14px; color: white; font-size: 13px; font-family: inherit; outline: none; }
  select option { background: #1a1a2e; color: #e0e0e0; }
  input:focus, select:focus { border-color: #00ff88; }
  input::placeholder { color: rgba(255,255,255,0.3); }
  .btn { cursor: pointer; font-weight: 600; transition: background 0.15s; }
  .btn-green { background: linear-gradient(135deg, #00ff88, #00cc66); color: #000; border: none; }
  .btn-green:hover { background: linear-gradient(135deg, #00cc66, #009944); }
  .btn-red { background: rgba(255,59,48,0.2); border-color: rgba(255,59,48,0.3); color: #ff3b30; }
  .btn-red:hover { background: rgba(255,59,48,0.3); }
  .btn-blue { background: rgba(66,133,244,0.2); border-color: rgba(66,133,244,0.3); color: #4285f4; }
  .btn-blue:hover { background: rgba(66,133,244,0.3); }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; white-space: nowrap; }
  th, td { text-align: left; padding: 8px 10px; font-size: 12px; }
  th { opacity: 0.4; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid rgba(255,255,255,0.08); }
  td { border-bottom: 1px solid rgba(255,255,255,0.04); }
  tr:hover td { background: rgba(255,255,255,0.02); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }
  .badge-online { background: rgba(0,255,136,0.15); color: #00ff88; }
  .badge-offline { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.3); }
  .msg { padding: 10px 14px; border-radius: 8px; margin-bottom: 10px; font-size: 13px; display: none; }
  .msg-ok { background: rgba(0,255,136,0.1); border: 1px solid rgba(0,255,136,0.2); color: #00ff88; }
  .msg-err { background: rgba(255,59,48,0.1); border: 1px solid rgba(255,59,48,0.2); color: #ff3b30; }
  .stats { display: flex; gap: 12px; margin-bottom: 16px; }
  .stat { flex: 1; background: rgba(255,255,255,0.04); border-radius: 10px; padding: 14px; text-align: center; }
  .stat-num { font-size: 28px; font-weight: 700; color: #00ff88; }
  .stat-label { font-size: 10px; opacity: 0.4; text-transform: uppercase; margin-top: 4px; }
  .actions { display: flex; gap: 6px; }
  .actions button { padding: 6px 10px; font-size: 11px; }
</style>
</head>
<body>
  <h1>🎮 Sweet Admin</h1>

  <div class="stats">
    <div class="stat"><div class="stat-num" id="st-users">-</div><div class="stat-label">Usuários</div></div>
    <div class="stat"><div class="stat-num" id="st-sessions">-</div><div class="stat-label">Sessões ativas</div></div>
  </div>

  <div id="msg" class="msg"></div>

  <h2>Criar Usuário</h2>
  <div class="card">
    <div class="form-row">
      <input id="f-user" placeholder="Usuário" style="flex:1">
      <input id="f-pin" placeholder="PIN (4-8 dígitos)" style="width:130px" maxlength="8">
    </div>
    <div class="form-row">
      <input id="f-discord" placeholder="Discord ID (opcional)" style="flex:1">
      <select id="f-estado" style="width:100px;">
        <option value="">Estado</option>
        <option value="AC">AC</option><option value="AL">AL</option><option value="AP">AP</option><option value="AM">AM</option>
        <option value="BA">BA</option><option value="CE">CE</option><option value="DF">DF</option><option value="ES">ES</option>
        <option value="GO">GO</option><option value="MA">MA</option><option value="MT">MT</option><option value="MS">MS</option>
        <option value="MG">MG</option><option value="PA">PA</option><option value="PB">PB</option><option value="PR">PR</option>
        <option value="PE">PE</option><option value="PI">PI</option><option value="RJ">RJ</option><option value="RN">RN</option>
        <option value="RS">RS</option><option value="RO">RO</option><option value="RR">RR</option><option value="SC">SC</option>
        <option value="SP">SP</option><option value="SE">SE</option><option value="TO">TO</option>
      </select>
      <button class="btn btn-green" onclick="createUser()">＋ Criar</button>
    </div>
  </div>

  <h2>Usuários</h2>
  <div class="card" style="padding:0;overflow:hidden;">
    <div class="table-wrap">
    <table>
      <thead><tr><th>#</th><th>Usuário</th><th>Discord</th><th>Tel</th><th>UF</th><th>HWID</th><th>Criado</th><th>Status</th><th></th></tr></thead>
      <tbody id="user-list"></tbody>
    </table>
    </div>
  </div>

<script>
  const KEY = new URLSearchParams(location.search).get('key') || '';

  function headers() { return { 'Content-Type': 'application/json', 'X-Admin-Key': KEY }; }

  function showMsg(text, ok) {
    const m = document.getElementById('msg');
    m.textContent = text;
    m.className = 'msg ' + (ok ? 'msg-ok' : 'msg-err');
    m.style.display = 'block';
    setTimeout(() => m.style.display = 'none', 4000);
  }

  async function load() {
    try {
      const res = await fetch('/admin/api/users?key=' + KEY);
      if (!res.ok) { document.body.innerHTML = '<h1 style="color:#ff3b30">Acesso negado</h1><p>Adicione ?key=SUA_CHAVE na URL</p>'; return; }
      const data = await res.json();
      document.getElementById('st-users').textContent = data.users.length;
      document.getElementById('st-sessions').textContent = data.active_sessions;
      const tbody = document.getElementById('user-list');
      tbody.innerHTML = '';
      data.users.forEach(u => {
        const tr = document.createElement('tr');
        const active = data.user_sessions[u.id] || 0;
        tr.innerHTML =
          '<td style="opacity:0.3">' + u.id + '</td>' +
          '<td><strong>' + esc(u.username) + '</strong></td>' +
          '<td style="opacity:0.5;font-size:11px">' + (u.discord_id || '—') + '</td>' +
          '<td style="opacity:0.5;font-size:11px">' + (u.phone || '<span style="opacity:0.3">—</span>') + '</td>' +
          '<td style="opacity:0.5;font-size:11px">' + (u.estado || '—') + '</td>' +
          '<td style="opacity:0.4;font-size:10px;font-family:monospace">' + (u.hwid ? u.hwid.substring(0,12) + '…' : '<span style="opacity:0.3">—</span>') + '</td>' +
          '<td style="opacity:0.4;font-size:11px">' + u.created_at + '</td>' +
          '<td><span class="badge ' + (active > 0 ? 'badge-online' : 'badge-offline') + '">' + (active > 0 ? 'Online' : 'Offline') + '</span></td>' +
          '<td class="actions">' +
            '<button class="btn btn-blue" onclick="resetPin(' + u.id + ',\\'' + esc(u.username) + '\\')">🔑 PIN</button>' +
            (u.hwid ? '<button class="btn btn-red" onclick="resetHwid(' + u.id + ',\\'' + esc(u.username) + '\\')">🖥 HWID</button>' : '') +
            '<button class="btn btn-red" onclick="clearData(' + u.id + ',\\'' + esc(u.username) + '\\')">🗑 Dados</button>' +
            '<button class="btn btn-red" onclick="deleteUser(' + u.id + ',\\'' + esc(u.username) + '\\')">✕</button>' +
          '</td>';
        tbody.appendChild(tr);
      });
    } catch(e) { showMsg('Erro ao carregar: ' + e.message, false); }
  }

  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  async function createUser() {
    const username = document.getElementById('f-user').value.trim();
    const pin = document.getElementById('f-pin').value.trim();
    const discord_id = document.getElementById('f-discord').value.trim();
    const estado = document.getElementById('f-estado').value;
    if (!username || !pin) { showMsg('Preencha usuário e PIN', false); return; }
    try {
      const res = await fetch('/admin/api/users', { method: 'POST', headers: headers(), body: JSON.stringify({ username, pin, discord_id, estado }) });
      const data = await res.json();
      if (res.ok) { showMsg('Usuário ' + username + ' criado!' + (data.phone ? ' Tel: ' + data.phone : ''), true); document.getElementById('f-user').value = ''; document.getElementById('f-pin').value = ''; document.getElementById('f-discord').value = ''; document.getElementById('f-estado').value = ''; load(); }
      else showMsg(data.error, false);
    } catch(e) { showMsg('Erro: ' + e.message, false); }
  }

  async function deleteUser(id, name) {
    if (!confirm('Deletar ' + name + '? Isso remove todas as sessões.')) return;
    try {
      const res = await fetch('/admin/api/users/' + id + '?key=' + KEY, { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) { showMsg(name + ' removido', true); load(); }
      else showMsg(data.error, false);
    } catch(e) { showMsg('Erro: ' + e.message, false); }
  }

  async function resetPin(id, name) {
    const pin = prompt('Novo PIN para ' + name + ' (4-8 dígitos):');
    if (!pin) return;
    try {
      const res = await fetch('/admin/api/users/' + id + '/pin', { method: 'PUT', headers: headers(), body: JSON.stringify({ pin }) });
      const data = await res.json();
      if (res.ok) { showMsg('PIN de ' + name + ' atualizado!', true); }
      else showMsg(data.error, false);
    } catch(e) { showMsg('Erro: ' + e.message, false); }
  }

  async function resetHwid(id, name) {
    if (!confirm('Resetar HWID de ' + name + '? Ele poderá logar de qualquer PC novamente (vincular novo dispositivo).')) return;
    try {
      const res = await fetch('/admin/api/users/' + id + '/hwid?key=' + KEY, { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) { showMsg('HWID de ' + name + ' resetado!', true); load(); }
      else showMsg(data.error, false);
    } catch(e) { showMsg('Erro: ' + e.message, false); }
  }

  async function clearData(id, name) {
    if (!confirm('Limpar TODOS os dados salvos de ' + name + '? (notas, wallpaper, configs)\\nIsso não pode ser desfeito!')) return;
    try {
      const res = await fetch('/admin/api/users/' + id + '/data?key=' + KEY, { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) { showMsg('Dados de ' + name + ' limpos! (' + data.deleted + ' registros removidos)', true); }
      else showMsg(data.error, false);
    } catch(e) { showMsg('Erro: ' + e.message, false); }
  }

  load();
</script>
</body>
</html>'''


def check_admin_key():
    key = request.args.get('key') or request.headers.get('X-Admin-Key', '')
    if key != ADMIN_KEY:
        return False
    return True


@app.route('/admin')
def admin_panel():
    if not check_admin_key():
        return 'Acesso negado. Use ?key=SUA_CHAVE', 403
    return render_template_string(ADMIN_HTML)


@app.route('/admin/api/users', methods=['GET'])
def admin_list_users():
    if not check_admin_key():
        return jsonify({'error': 'Acesso negado'}), 403

    conn = get_db()
    users = conn.execute('SELECT id, username, discord_id, hwid, phone, estado, created_at FROM users ORDER BY id').fetchall()
    sessions = conn.execute('SELECT user_id, COUNT(*) as cnt FROM sessions GROUP BY user_id').fetchall()
    total_sessions = conn.execute('SELECT COUNT(*) as cnt FROM sessions').fetchone()['cnt']
    conn.close()

    user_sessions = {s['user_id']: s['cnt'] for s in sessions}

    return jsonify({
        'users': [dict(u) for u in users],
        'user_sessions': user_sessions,
        'active_sessions': total_sessions,
    })


@app.route('/admin/api/users', methods=['POST'])
def admin_create_user():
    if not check_admin_key():
        return jsonify({'error': 'Acesso negado'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    result, status = validate_and_create_user(data)
    return jsonify(result), status


@app.route('/admin/api/users/<int:user_id>', methods=['DELETE'])
def admin_delete_user(user_id):
    if not check_admin_key():
        return jsonify({'error': 'Acesso negado'}), 403

    conn = get_db()
    conn.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/admin/api/users/<int:user_id>/pin', methods=['PUT'])
def admin_reset_pin(user_id):
    if not check_admin_key():
        return jsonify({'error': 'Acesso negado'}), 403

    data = request.get_json()
    pin = (data.get('pin') or '').strip() if data else ''
    if len(pin) < 4 or len(pin) > 8 or not pin.isdigit():
        return jsonify({'error': 'PIN deve ter 4-8 dígitos numéricos'}), 400

    pin_hash = bcrypt.hashpw(pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    conn = get_db()
    conn.execute('UPDATE users SET pin_hash = ? WHERE id = ?', (pin_hash, user_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/admin/api/users/<int:user_id>/hwid', methods=['DELETE'])
def admin_reset_hwid(user_id):
    if not check_admin_key():
        return jsonify({'error': 'Acesso negado'}), 403

    conn = get_db()
    conn.execute("UPDATE users SET hwid = '' WHERE id = ?", (user_id,))
    conn.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/admin/api/users/<int:user_id>/data', methods=['DELETE'])
def admin_clear_user_data(user_id):
    if not check_admin_key():
        return jsonify({'error': 'Acesso negado'}), 403

    conn = get_db()
    cursor = conn.execute('DELETE FROM user_data WHERE user_id = ?', (user_id,))
    deleted = cursor.rowcount
    conn.execute('UPDATE users SET balance = 0 WHERE id = ?', (user_id,))
    conn.execute('DELETE FROM transactions WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'deleted': deleted})


# ===== BANCO VIRTUAL =====

@app.route('/api/bank/balance', methods=['GET'])
def bank_balance():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    conn = get_db()
    row = conn.execute('SELECT balance FROM users WHERE id = ?', (user['id'],)).fetchone()
    conn.close()
    return jsonify({'balance': row['balance'] if row else 0})


@app.route('/api/bank/deposit', methods=['POST'])
def bank_deposit():
    """Deposita ganhos de frete na conta."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    amount = data.get('amount', 0)
    description = (data.get('description') or 'Frete')[:100]

    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({'error': 'Valor inválido'}), 400

    conn = get_db()
    conn.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (amount, user['id']))
    conn.execute(
        'INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
        (user['id'], 'deposit', amount, description)
    )
    conn.commit()
    row = conn.execute('SELECT balance FROM users WHERE id = ?', (user['id'],)).fetchone()
    conn.close()
    return jsonify({'success': True, 'balance': row['balance']})


@app.route('/api/bank/pix', methods=['POST'])
def bank_pix():
    """Envia PIX para outro usuário."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    to_username = (data.get('to') or '').strip()
    amount = data.get('amount', 0)

    if not to_username:
        return jsonify({'error': 'Destinatário obrigatório'}), 400
    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({'error': 'Valor inválido'}), 400
    if to_username.lower() == user['username'].lower():
        return jsonify({'error': 'Não pode enviar PIX para si mesmo'}), 400

    conn = get_db()
    sender = conn.execute('SELECT id, username, balance FROM users WHERE id = ?', (user['id'],)).fetchone()
    receiver = conn.execute('SELECT id, username FROM users WHERE username = ? COLLATE NOCASE', (to_username,)).fetchone()

    if not receiver:
        conn.close()
        return jsonify({'error': 'Usuário não encontrado'}), 404

    if sender['balance'] < amount:
        conn.close()
        return jsonify({'error': 'Saldo insuficiente'}), 400

    # Atomic transfer
    conn.execute('UPDATE users SET balance = balance - ? WHERE id = ?', (amount, sender['id']))
    conn.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (amount, receiver['id']))

    desc_out = f'PIX para {receiver["username"]}'
    desc_in = f'PIX de {sender["username"]}'

    conn.execute(
        'INSERT INTO transactions (user_id, type, amount, description, from_user, to_user) VALUES (?, ?, ?, ?, ?, ?)',
        (sender['id'], 'pix_out', amount, desc_out, sender['username'], receiver['username'])
    )
    conn.execute(
        'INSERT INTO transactions (user_id, type, amount, description, from_user, to_user) VALUES (?, ?, ?, ?, ?, ?)',
        (receiver['id'], 'pix_in', amount, desc_in, sender['username'], receiver['username'])
    )
    conn.commit()

    new_balance = conn.execute('SELECT balance FROM users WHERE id = ?', (sender['id'],)).fetchone()['balance']
    conn.close()

    return jsonify({'success': True, 'balance': new_balance, 'to': receiver['username']})


@app.route('/api/bank/transactions', methods=['GET'])
def bank_transactions():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    conn = get_db()
    rows = conn.execute(
        'SELECT type, amount, description, from_user, to_user, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 50',
        (user['id'],)
    ).fetchall()
    conn.close()

    return jsonify({'transactions': [dict(r) for r in rows]})


# ===== CHAT =====

@app.route('/api/chat/send', methods=['POST'])
def chat_send():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    to_username = (data.get('to') or '').strip()
    content = (data.get('content') or '').strip()

    if not to_username:
        return jsonify({'error': 'Destinatário obrigatório'}), 400
    if not content or len(content) > 500:
        return jsonify({'error': 'Mensagem inválida (1-500 caracteres)'}), 400
    if to_username.lower() == user['username'].lower():
        return jsonify({'error': 'Não pode enviar mensagem para si mesmo'}), 400

    conn = get_db()
    receiver = conn.execute('SELECT id, username FROM users WHERE username = ? COLLATE NOCASE', (to_username,)).fetchone()
    if not receiver:
        conn.close()
        return jsonify({'error': 'Usuário não encontrado'}), 404

    conn.execute(
        'INSERT INTO messages (from_user_id, to_user_id, content) VALUES (?, ?, ?)',
        (user['id'], receiver['id'], content)
    )
    conn.commit()
    msg = conn.execute('SELECT id, created_at FROM messages WHERE rowid = last_insert_rowid()').fetchone()
    conn.close()

    return jsonify({
        'success': True,
        'message': {
            'id': msg['id'],
            'from': user['username'],
            'to': receiver['username'],
            'content': content,
            'mine': True,
            'created_at': msg['created_at'],
        }
    })


@app.route('/api/chat/conversations', methods=['GET'])
def chat_conversations():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    conn = get_db()
    rows = conn.execute('''
        SELECT
            u.username,
            m.content AS last_message,
            m.created_at AS last_time,
            m.from_user_id,
            (SELECT COUNT(*) FROM messages
             WHERE from_user_id = u.id AND to_user_id = ? AND read = 0) AS unread
        FROM users u
        JOIN messages m ON m.id = (
            SELECT id FROM messages
            WHERE (from_user_id = ? AND to_user_id = u.id)
               OR (from_user_id = u.id AND to_user_id = ?)
            ORDER BY created_at DESC LIMIT 1
        )
        WHERE u.id != ?
        ORDER BY m.created_at DESC
    ''', (user['id'], user['id'], user['id'], user['id'])).fetchall()
    conn.close()

    convos = []
    for r in rows:
        convos.append({
            'username': r['username'],
            'lastMessage': r['last_message'][:60] if r['last_message'] else '',
            'lastTime': r['last_time'],
            'unread': r['unread'],
            'isMine': r['from_user_id'] == user['id'],
        })

    return jsonify({'conversations': convos})


@app.route('/api/chat/messages/<username>', methods=['GET'])
def chat_messages(username):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    conn = get_db()
    other = conn.execute('SELECT id, username FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
    if not other:
        conn.close()
        return jsonify({'error': 'Usuário não encontrado'}), 404

    # Mark as read
    conn.execute(
        'UPDATE messages SET read = 1 WHERE from_user_id = ? AND to_user_id = ? AND read = 0',
        (other['id'], user['id'])
    )
    conn.commit()

    after_id = request.args.get('after', 0, type=int)
    rows = conn.execute('''
        SELECT id, from_user_id, content, created_at FROM messages
        WHERE ((from_user_id = ? AND to_user_id = ?) OR (from_user_id = ? AND to_user_id = ?))
          AND id > ?
        ORDER BY created_at ASC LIMIT 100
    ''', (user['id'], other['id'], other['id'], user['id'], after_id)).fetchall()
    conn.close()

    msgs = []
    for r in rows:
        msgs.append({
            'id': r['id'],
            'content': r['content'],
            'mine': r['from_user_id'] == user['id'],
            'created_at': r['created_at'],
        })

    return jsonify({'messages': msgs, 'username': other['username']})


@app.route('/api/chat/unread', methods=['GET'])
def chat_unread():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    conn = get_db()
    row = conn.execute(
        'SELECT COUNT(*) as cnt FROM messages WHERE to_user_id = ? AND read = 0',
        (user['id'],)
    ).fetchone()
    conn.close()
    return jsonify({'unread': row['cnt']})


@app.route('/api/chat/users', methods=['GET'])
def chat_users():
    """List all users for starting a new conversation."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    conn = get_db()
    rows = conn.execute('SELECT username FROM users WHERE id != ? ORDER BY username', (user['id'],)).fetchall()
    conn.close()
    return jsonify({'users': [r['username'] for r in rows]})


# ===== AVATAR =====

@app.route('/api/profile/avatar', methods=['PUT'])
def update_avatar():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    avatar_url = (data.get('avatar_url') or '').strip()[:500]
    conn = get_db()
    conn.execute('UPDATE users SET avatar_url = ? WHERE id = ?', (avatar_url, user['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'avatar_url': avatar_url})


@app.route('/api/profile/avatar', methods=['GET'])
def get_avatar():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    return jsonify({'avatar_url': user['avatar_url'] or ''})


@app.route('/api/profile/avatar/<username>', methods=['GET'])
def get_user_avatar(username):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    conn = get_db()
    row = conn.execute('SELECT avatar_url FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Usuário não encontrado'}), 404
    return jsonify({'avatar_url': row['avatar_url'] or ''})


# ===== CONTACTS =====

@app.route('/api/contacts', methods=['GET'])
def get_contacts():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    conn = get_db()
    rows = conn.execute('''
        SELECT u.username, u.avatar_url, u.phone FROM contacts c
        JOIN users u ON c.contact_user_id = u.id
        WHERE c.user_id = ? ORDER BY u.username
    ''', (user['id'],)).fetchall()
    conn.close()
    return jsonify({'contacts': [{'username': r['username'], 'avatar_url': r['avatar_url'] or '', 'phone': r['phone'] or ''} for r in rows]})


@app.route('/api/contacts', methods=['POST'])
def add_contact():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    username = (data.get('username') or '').strip()
    if not username:
        return jsonify({'error': 'Nome de usuário obrigatório'}), 400
    if username.lower() == user['username'].lower():
        return jsonify({'error': 'Não pode adicionar a si mesmo'}), 400
    conn = get_db()
    target = conn.execute('SELECT id FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': 'Usuário não encontrado'}), 404
    try:
        conn.execute('INSERT INTO contacts (user_id, contact_user_id) VALUES (?, ?)', (user['id'], target['id']))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Contato já adicionado'}), 409
    conn.close()
    return jsonify({'success': True})


@app.route('/api/contacts/<username>', methods=['DELETE'])
def remove_contact(username):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    conn = get_db()
    target = conn.execute('SELECT id FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': 'Usuário não encontrado'}), 404
    conn.execute('DELETE FROM contacts WHERE user_id = ? AND contact_user_id = ?', (user['id'], target['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/contacts/search', methods=['GET'])
def search_users():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    q = (request.args.get('q') or '').strip()
    q_digits = ''.join(c for c in q if c.isdigit())
    if len(q_digits) < 4 and len(q) < 4:
        return jsonify({'users': []})
    conn = get_db()
    search_q = q_digits if q_digits else q
    rows = conn.execute('''
        SELECT username, avatar_url, phone FROM users
        WHERE id != ? AND phone != '' AND
        REPLACE(REPLACE(REPLACE(REPLACE(phone, '(', ''), ')', ''), '-', ''), ' ', '') LIKE ?
        ORDER BY username LIMIT 20
    ''', (user['id'], f'%{search_q}%')).fetchall()
    conn.close()
    return jsonify({'users': [{'username': r['username'], 'avatar_url': r['avatar_url'] or '', 'phone': r['phone'] or ''} for r in rows]})


# ===== GROUPS =====

@app.route('/api/groups', methods=['GET'])
def get_groups():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    conn = get_db()
    rows = conn.execute('''
        SELECT g.id, g.name, g.avatar_url, g.owner_id,
            (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
            (SELECT content FROM group_messages WHERE group_id = g.id ORDER BY created_at DESC LIMIT 1) as last_message,
            (SELECT created_at FROM group_messages WHERE group_id = g.id ORDER BY created_at DESC LIMIT 1) as last_time,
            (SELECT u2.username FROM group_messages gm2 JOIN users u2 ON gm2.from_user_id = u2.id WHERE gm2.group_id = g.id ORDER BY gm2.created_at DESC LIMIT 1) as last_sender
        FROM groups_ g
        JOIN group_members gm ON gm.group_id = g.id
        WHERE gm.user_id = ?
        ORDER BY COALESCE(last_time, g.created_at) DESC
    ''', (user['id'],)).fetchall()
    conn.close()
    return jsonify({'groups': [dict(r) for r in rows]})


@app.route('/api/groups', methods=['POST'])
def create_group():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    name = (data.get('name') or '').strip()
    if not name or len(name) > 30:
        return jsonify({'error': 'Nome do grupo inválido (1-30 chars)'}), 400
    members = data.get('members', [])
    if not isinstance(members, list):
        return jsonify({'error': 'Lista de membros inválida'}), 400
    avatar_url = (data.get('avatar_url') or '').strip()[:500]

    conn = get_db()
    cursor = conn.execute('INSERT INTO groups_ (name, avatar_url, owner_id) VALUES (?, ?, ?)',
                          (name, avatar_url, user['id']))
    group_id = cursor.lastrowid
    # Add creator as member
    conn.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)', (group_id, user['id']))
    # Add other members
    for m in members:
        m_user = conn.execute('SELECT id FROM users WHERE username = ? COLLATE NOCASE', (m,)).fetchone()
        if m_user and m_user['id'] != user['id']:
            try:
                conn.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)', (group_id, m_user['id']))
            except sqlite3.IntegrityError:
                pass
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'group_id': group_id})


@app.route('/api/groups/<int:group_id>/messages', methods=['GET'])
def get_group_messages(group_id):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    conn = get_db()
    # Check membership
    member = conn.execute('SELECT id FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user['id'])).fetchone()
    if not member:
        conn.close()
        return jsonify({'error': 'Não é membro do grupo'}), 403
    after_id = request.args.get('after', 0, type=int)
    rows = conn.execute('''
        SELECT gm.id, gm.from_user_id, u.username as sender, gm.content, gm.created_at
        FROM group_messages gm JOIN users u ON gm.from_user_id = u.id
        WHERE gm.group_id = ? AND gm.id > ?
        ORDER BY gm.created_at ASC LIMIT 100
    ''', (group_id, after_id)).fetchall()
    conn.close()
    return jsonify({'messages': [
        {'id': r['id'], 'sender': r['sender'], 'content': r['content'],
         'mine': r['from_user_id'] == user['id'], 'created_at': r['created_at']}
        for r in rows
    ]})


@app.route('/api/groups/<int:group_id>/messages', methods=['POST'])
def send_group_message(group_id):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    content = (data.get('content') or '').strip()
    if not content or len(content) > 500:
        return jsonify({'error': 'Mensagem inválida (1-500 chars)'}), 400
    conn = get_db()
    member = conn.execute('SELECT id FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user['id'])).fetchone()
    if not member:
        conn.close()
        return jsonify({'error': 'Não é membro do grupo'}), 403
    conn.execute('INSERT INTO group_messages (group_id, from_user_id, content) VALUES (?, ?, ?)',
                 (group_id, user['id'], content))
    conn.commit()
    msg = conn.execute('SELECT id, created_at FROM group_messages WHERE rowid = last_insert_rowid()').fetchone()
    conn.close()
    return jsonify({'success': True, 'message': {
        'id': msg['id'], 'sender': user['username'], 'content': content,
        'mine': True, 'created_at': msg['created_at']
    }})


@app.route('/api/groups/<int:group_id>/members', methods=['GET'])
def get_group_members(group_id):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    conn = get_db()
    member = conn.execute('SELECT id FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user['id'])).fetchone()
    if not member:
        conn.close()
        return jsonify({'error': 'Não é membro do grupo'}), 403
    group = conn.execute('SELECT owner_id FROM groups_ WHERE id = ?', (group_id,)).fetchone()
    rows = conn.execute('''
        SELECT u.username, u.avatar_url FROM group_members gm
        JOIN users u ON gm.user_id = u.id WHERE gm.group_id = ?
        ORDER BY u.username
    ''', (group_id,)).fetchall()
    conn.close()
    return jsonify({'members': [
        {'username': r['username'], 'avatar_url': r['avatar_url'] or '', 'is_owner': group and r['username'] == user['username']}
        for r in rows
    ], 'owner_id': group['owner_id'] if group else 0})


@app.route('/api/groups/<int:group_id>/members', methods=['POST'])
def add_group_member(group_id):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400
    username = (data.get('username') or '').strip()
    conn = get_db()
    group = conn.execute('SELECT owner_id FROM groups_ WHERE id = ?', (group_id,)).fetchone()
    if not group or group['owner_id'] != user['id']:
        conn.close()
        return jsonify({'error': 'Apenas o dono pode adicionar membros'}), 403
    target = conn.execute('SELECT id FROM users WHERE username = ? COLLATE NOCASE', (username,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': 'Usuário não encontrado'}), 404
    try:
        conn.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)', (group_id, target['id']))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Já é membro'}), 409
    conn.close()
    return jsonify({'success': True})


# ===== USER DATA SYNC =====

ALLOWED_DATA_KEYS = {'pj_notas', 'pj_wallpaper', 'pj_wallpaper_fit'}
MAX_DATA_SIZE = 500_000  # 500KB per key

@app.route('/api/userdata/save', methods=['POST'])
def userdata_save():
    """Save user data to the server (notas, settings, etc.)."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    key = (data.get('key') or '').strip()
    value = data.get('value', '')

    if key not in ALLOWED_DATA_KEYS:
        return jsonify({'error': 'Chave não permitida'}), 400
    if len(value) > MAX_DATA_SIZE:
        return jsonify({'error': 'Dados muito grandes'}), 413

    conn = get_db()
    conn.execute('''
        INSERT INTO user_data (user_id, data_key, data_value, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, data_key) DO UPDATE SET
            data_value = excluded.data_value,
            updated_at = CURRENT_TIMESTAMP
    ''', (user['id'], key, value))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/userdata/load', methods=['GET'])
def userdata_load():
    """Load user data from the server."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    key = request.args.get('key', '').strip()
    if key and key not in ALLOWED_DATA_KEYS:
        return jsonify({'error': 'Chave não permitida'}), 400

    conn = get_db()
    if key:
        row = conn.execute(
            'SELECT data_value FROM user_data WHERE user_id = ? AND data_key = ?',
            (user['id'], key)
        ).fetchone()
        conn.close()
        return jsonify({'success': True, 'value': row['data_value'] if row else None})
    else:
        rows = conn.execute(
            'SELECT data_key, data_value FROM user_data WHERE user_id = ?',
            (user['id'],)
        ).fetchall()
        conn.close()
        result = {row['data_key']: row['data_value'] for row in rows}
        return jsonify({'success': True, 'data': result})


@app.route('/api/userdata/delete', methods=['POST'])
def userdata_delete():
    """Delete a user data key from the server."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    data = request.get_json()
    key = (data.get('key') or '').strip() if data else ''
    if key not in ALLOWED_DATA_KEYS:
        return jsonify({'error': 'Chave não permitida'}), 400

    conn = get_db()
    conn.execute('DELETE FROM user_data WHERE user_id = ? AND data_key = ?', (user['id'], key))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ===== DISCORD WEBHOOK (server-side) =====

def send_discord_webhook(payload_dict, webhook_url):
    """Send a payload to a Discord webhook."""
    if not webhook_url:
        return False
    try:
        data = json_lib.dumps(payload_dict).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'SweetSystem/1.0',
            },
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status in (200, 204)
    except Exception as e:
        print(f'Discord webhook error: {e}')
        return False


@app.route('/api/discord/pedagio', methods=['POST'])
def discord_pedagio():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    city_src = data.get('citySrc', 'Desconhecida')
    city_dst = data.get('cityDst', 'Desconhecida')
    cargo = data.get('cargo', '')
    placa = data.get('placa', '')
    placa_pais = data.get('placaPais', '')
    valor = data.get('valor', '0.00')
    motorista = data.get('motorista', '')
    tipo = data.get('tipo', 'Entrada')

    discord_id = user['discord_id']
    content = f'||<@{discord_id}>||' if discord_id else ''

    # Montar descrição
    desc_lines = []
    desc_lines.append(f'> # **Valor: R${valor}**')
    if city_src and city_dst and city_src != 'Desconhecida' and city_dst != 'Desconhecida':
        desc_lines.append(f'> **Entrega para:** {city_src} → {city_dst}')
    if cargo and cargo != 'Nenhuma':
        desc_lines.append(f'> **Carga:** {cargo}')
    if placa:
        placa_str = f'{placa} ({placa_pais})' if placa_pais else placa
        desc_lines.append(f'> **Placa:** {placa_str}')
    if motorista:
        desc_lines.append(f'> **Motorista:** {motorista}')

    embed = {
        'title': '💳 - Cobrança realizada com sucesso',
        'description': '\n'.join(desc_lines),
        'color': 14027602,
        'footer': {'text': 'Sem Parar - System'},
    }
    if DISCORD_EMBED_IMAGE:
        embed['image'] = {'url': DISCORD_EMBED_IMAGE}

    send_discord_webhook({'content': content, 'embeds': [embed]}, DISCORD_WEBHOOK_PEDAGIO)
    return jsonify({'success': True})


@app.route('/api/discord/nota', methods=['POST'])
def discord_nota():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    nota_text = data.get('nota', '')
    if not nota_text:
        return jsonify({'error': 'Nota vazia'}), 400

    discord_id = user['discord_id']
    mention = f'<@{discord_id}>\n' if discord_id else ''

    send_discord_webhook({
        'content': mention + '```\n' + nota_text + '\n```'
    }, DISCORD_WEBHOOK_NOTA)
    return jsonify({'success': True})


def send_discord_webhook_image(image_bytes, filename, content, webhook_url):
    """Send an image file to a Discord webhook via multipart/form-data."""
    if not webhook_url:
        return False
    try:
        import io
        boundary = '----WebKitFormBoundary' + secrets.token_hex(8)
        body = io.BytesIO()

        # File part
        body.write(f'--{boundary}\r\n'.encode())
        body.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
        body.write(b'Content-Type: image/png\r\n\r\n')
        body.write(image_bytes)
        body.write(b'\r\n')

        # payload_json part
        payload = json_lib.dumps({'content': content})
        body.write(f'--{boundary}\r\n'.encode())
        body.write(b'Content-Disposition: form-data; name="payload_json"\r\n')
        body.write(b'Content-Type: application/json\r\n\r\n')
        body.write(payload.encode())
        body.write(b'\r\n')

        body.write(f'--{boundary}--\r\n'.encode())
        body_bytes = body.getvalue()

        req = urllib.request.Request(
            webhook_url,
            data=body_bytes,
            headers={
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'User-Agent': 'SweetSystem/1.0',
            },
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status in (200, 204)
    except Exception as e:
        print(f'Discord webhook image error: {e}')
        return False


@app.route('/api/discord/nota-image', methods=['POST'])
def discord_nota_image():
    import base64
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON inválido'}), 400

    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    user = verify_token(token)
    if not user:
        return jsonify({'error': 'Não autenticado'}), 401

    image_b64 = data.get('image', '')
    numero = data.get('numero', 0)
    if not image_b64:
        return jsonify({'error': 'Imagem vazia'}), 400

    # Limitar tamanho (max ~8MB base64 = ~6MB imagem)
    if len(image_b64) > 8_000_000:
        return jsonify({'error': 'Imagem muito grande'}), 413

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        return jsonify({'error': 'Base64 inválido'}), 400

    discord_id = user['discord_id']
    mention = f'<@{discord_id}>' if discord_id else ''
    content = f'{mention} 📋 **CT-e Frete #{numero}**'
    filename = f'cte_frete_{numero}.png'

    send_discord_webhook_image(image_bytes, filename, content, DISCORD_WEBHOOK_NOTA)
    return jsonify({'success': True})


# ===== AUTO-UPDATE =====
UPDATES_DIR = os.path.join(os.path.dirname(__file__), 'updates')
os.makedirs(UPDATES_DIR, exist_ok=True)

@app.route('/updates/<path:filename>', methods=['GET'])
def serve_update(filename):
    return send_from_directory(UPDATES_DIR, filename)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=3000)
