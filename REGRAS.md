# REGRAS — Áreas Sensíveis do Projeto

> Leia este arquivo antes de pedir para qualquer IA alterar código.
> Estas áreas contêm correções críticas que resolveram bugs reais relatados por usuários.
> **Não remova, simplifique nem refatore estas seções sem entender o motivo de cada uma.**

---

## 1. main.js — Sistema anti-tela-preta (GPU)

**Linhas ~20–40 e ~358–380**

```js
const GPU_CRASH_FLAG = path.join(os.tmpdir(), 'cll-gpu-crash.flag');
const _gpuCrashMode = fs.existsSync(GPU_CRASH_FLAG);
if (_gpuCrashMode) {
  app.commandLine.appendSwitch('disable-gpu');
  ...
} else {
  app.commandLine.appendSwitch('in-process-gpu');
  app.commandLine.appendSwitch('disable-direct-composition');
  app.commandLine.appendSwitch('use-angle', 'd3d11');
  ...
}
```

**Por que existe:** GPUs Intel HD antigas e máquinas com drivers desatualizados renderizam a janela transparente completamente preta sem crashar — o Electron não detecta como erro. O sistema:
1. Verifica `app.getGPUFeatureStatus()` logo no `whenReady()` — se compositing não estiver `"enabled"`, escreve a flag e chama `app.relaunch()` automaticamente (o usuário não precisa fazer nada)
2. Se o processo GPU crashar durante a sessão (`child-process-gone`), escreve a flag para a próxima abertura
3. Na próxima abertura com a flag presente, usa `--disable-gpu` (software rendering) que funciona em qualquer máquina

**Não remova:** nenhuma das flags `appendSwitch`. Cada uma resolve um hardware específico.
- `in-process-gpu` → evita tela preta por crash silencioso do processo GPU separado
- `disable-direct-composition` → resolve conflito com DWM em Intel HD/UHD no Win10
- `use-angle d3d11` → mais compatível que o padrão em GPUs antigas
- `backgroundColor: '#00000000'` na BrowserWindow → sem isso o Chromium renderiza preto antes do HTML carregar

---

## 2. main.js — Atalhos PX via GetAsyncKeyState (polling)

**Linhas ~89 e ~574–640 (setInterval de 60ms)**

```js
const _pxShortcuts = { ptt: null, toggle: null };
// ...
function acceleratorToVk(accel) { ... }
// setInterval a cada 60ms lê GetAsyncKeyState
```

**Por que existe:** Listeners de teclado DOM (`keydown`, `keyup`) só funcionam quando a janela Electron está em foco. Como o overlay é transparente e o usuário está jogando, a janela nunca tem foco. O polling via `GetAsyncKeyState` no processo principal funciona **independente de foco**.

**Não troque** por `globalShortcut` do Electron — conflita com jogos e pode ser bloqueado por anti-cheat.
**Não troque** por event listeners no renderer — não funciona sem foco.

---

## 3. main.js — Seletor de monitor (displays-get)

**Handler IPC `displays-get`**

**Por que existe:** Windows às vezes reporta monitores virtuais mesmo com 1 monitor físico. Se o `preferredDisplayId` já está salvo no `config.json` e o monitor ainda está conectado, o handler retorna direto sem abrir o picker — evitando a tela de seleção desnecessária toda vez que o app abre.

---

## 4. overlay.html — Sistema free/premium

**Linha ~4642: `IS_FREE = (loggedInUser.plan !== 'premium')`**
**Linha ~5252–5253: remoção dos ícones premium**
**Atributo `data-premium="true"` em todos os app-icons premium**

Apps premium (todos devem ter `data-premium="true"`):
- messages, notas, banco, yt, gallery, cmc, **px** (Rádio PX), musica, trs, documentos

**Atenção:** Se adicionar um novo app que é premium, **obrigatoriamente** adicione `data-premium="true"` no `div.app-icon`. Sem isso o app aparece para usuários free.

---

## 5. overlay.html — Atalhos PX no renderer

**Função `initPxShortcuts()` e `pxSaveShortcuts()`**

Usam `window.pxShortcutApi.set(shortcuts)` para sincronizar com o main.js.
**Não troque** por localStorage puro — o main.js precisa receber os shortcuts via IPC para o polling do GetAsyncKeyState funcionar.

---

## 6. preload.js — pxShortcutApi

```js
window.pxShortcutApi = {
  set: (s) => ipcRenderer.invoke('px-shortcuts-set', s),
  onPttStart: (cb) => ipcRenderer.on('px-ptt-start', cb),
  onPttStop:  (cb) => ipcRenderer.on('px-ptt-stop',  cb),
  onToggle:   (cb) => ipcRenderer.on('px-ptt-toggle', cb)
}
```

**Não remova.** É a ponte entre o polling do main.js e o renderer do rádio PX.

---

## 7. server.py — TTL de áudios de chat

**Rota `/api/chat/send` (~linha 2596)**

```python
is_audio = content.startswith('[audio mime=') and content.endswith('[/audio]')
# max_len = 120000 para áudio
# DELETE FROM messages WHERE content LIKE '[audio%' AND datetime < now - 24h
```

**Por que existe:** Áudios são armazenados como base64 no SQLite (sem arquivos no disco). A limpeza TTL de 24h acontece a cada mensagem enviada para evitar crescimento ilimitado do banco. **Não remova o bloco de limpeza TTL.**

---

## 8. overlay.html — waRenderContent

**Função `waRenderContent(content)`**

Parseia dois formatos especiais além de texto:
- `[photo]BASE64[/photo]` → `<img>`
- `[audio mime=TYPE]BASE64[/audio]` → player HTML5 leve

**Não simplifique** para só texto — quebraria todas as fotos e áudios já enviados no chat.

---

## 9. main.js — Recuperação automática de travamento do renderer

**Linhas ~828–862**

```js
win.webContents.on('render-process-gone', ...)   // renderer crashou → reload em 1s
win.webContents.on('did-fail-load', ...)          // falha ao carregar HTML → retry em 1.5s
win.webContents.on('unresponsive', ...)           // travado por 5s → forcefullyCrashRenderer()
```

**Por que existe:** Em máquinas lentas ou com pouca RAM o renderer pode travar silenciosamente sem mostrar erro. O `unresponsive` detecta isso e força um crash controlado — que o `render-process-gone` pega e recarrega automaticamente.

**Não remova** nenhum dos três handlers. Eles formam uma cadeia de recuperação.

---

## 10. main.js — HWID (identificador de máquina)

**Função `getHwid()` (~linha 273)**

```js
execSync('reg query "HKLM\\SOFTWARE\\Microsoft\\Cryptography" /v MachineGuid', ...)
cachedHwid = crypto.createHash('sha256').update(guid).digest('hex').substring(0, 32);
```

**Por que existe:** O HWID é enviado junto com o diagnóstico de boot e é usado para identificar a máquina do usuário com problemas. Usa o `MachineGuid` do registro do Windows (hash SHA256 — nunca o valor bruto) para evitar exposição de dados. O fallback `"unknown-" + randomBytes` garante que o app nunca crasha mesmo em máquinas sem permissão de registro.

**Não troque** por `os.hostname()` ou MAC address — são instáveis (mudam com VPN/VM).

---

## 11. main.js — Protocolo app:// (origem do localStorage)

**Linhas ~14–17 e ~377–383**

```js
protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
// ...
win.loadURL('app://./overlay.html');
```

**Por que existe:** Se o app fosse carregado via `file://`, o caminho de instalação faria parte da origem — cada reinstalação em pasta diferente seria uma origem diferente e o `localStorage` seria apagado. O protocolo `app://` garante origem fixa `app://` independente de onde o app está instalado.

**Não troque** por `file://` ou `loadFile()`. Quebraria persistência de login, preferências e shortcuts de todos os usuários ao atualizar.

---

## 12. main.js — Segurança Electron (webPreferences)

**Linhas ~403–407**

```js
nodeIntegration: false,
contextIsolation: true,
preload: path.join(__dirname, 'preload.js')
```

**Não habilite** `nodeIntegration: true` — daria ao renderer acesso total ao Node.js, o que é uma vulnerabilidade crítica (OWASP). Toda comunicação com o main process deve ser via `contextBridge` no `preload.js`.

---

## 13. telemetry.js — Leitura via Shared Memory (scs-sdk-plugin)

**Linhas ~7–26**

```js
MapViewOfFile(handle, FILE_MAP_READ, ...)  // leitura da memória compartilhada do ETS2/ATS
```

**Por que existe:** O ETS2/ATS expõe dados de telemetria via memória compartilhada usando o `scs-sdk-plugin`. A leitura é feita diretamente via `MapViewOfFile` da `kernel32.dll` usando `koffi` (FFI nativo), sem injeção de processo.

**Offsets críticos (não altere sem confirmar no jogo):**

| Offset | Campo | Conversão |
|--------|-------|-----------|
| `0x3B4` | speed (m/s) | × 3.6 = km/h |
| `0x3B8` | RPM | direto |
| `0x3DC` | cruise control (m/s) | × 3.6 = km/h |
| `0x3E8` | fuel (litros) | direto |
| `0x2C0` | fuelCapacity | direto |
| `0x3EC` | **fuelAvgConsumption (L/km)** | × 100 = L/100km — **SÓ quando speedMs > 1** |
| `0x3F0` | fuelRange (km) | direto |
| `0x42C` | speedLimit (m/s) | × 3.6 = km/h |
| `0x424` | routeDistance (m) | direto |
| `0x428` | routeTime (s) | direto |
| `0x420` | odometer | ⚠️ não confiável para cálculos acumulados |

**Atenção `fuelAvgConsumption`:** O valor nativo está em **L/km**, não L/m nem L/100km. Multiplicar por 100 para exibir. Parado (speedMs ≤ 1) retorna valores absurdos — sempre retornar `null` nesse caso.

---

## 14. overlay.html — Badge de não lidos do WhatsApp

**Funções `pollUnreadOnce()` e `startChatPolling()` (~linhas 9254–9650)**

**Por que existe:** O badge pode travar quando o polling recebe HTTP 429 (rate limit). A correção:
- Em `pollUnreadOnce()`, um `429` **não** para o timer — apenas pula aquela rodada
- Ao abrir o app de mensagens e ao iniciar polling, chama `pollUnreadOnce()` imediatamente (sync) para o badge atualizar sem esperar o intervalo
- Toasts de nova mensagem são suprimidos enquanto `currentPage` é `'messages'` ou `'wa-chat'`

**Não "simplifique"** o handler de 429 para parar o polling — vai travar o badge para sempre até reiniciar o app.

---

## 15. server.py — `require_premium` e `SESSION_TTL`

**Linhas ~42, ~558–589**

```python
SESSION_TTL = 86400  # 24h — tokens expiram
def verify_token(token): ...   # verifica token + idade
def require_premium(user): ... # retorna 403 se plan != 'premium'
```

**Não remova** o check de `SESSION_TTL` em `verify_token` — sem ele tokens antigos nunca expiram. O `require_premium` deve ser chamado em **todas** as rotas de funcionalidade premium antes de qualquer lógica de negócio.

---

## 16. main.js — Anti-duplicata no Alt+Tab (transparent + frameless)

**Linhas antes do `app.whenReady()` e logo após `new BrowserWindow(...)`**

```js
// ANTES do app.whenReady():
app.setAppUserModelId('com.sweeet.phoneproject');

// Logo após new BrowserWindow():
win.setAppDetails({ appId: 'com.sweeet.phoneproject' });
```

**Por que existe:** Janelas `transparent: true` + `frame: false` + `alwaysOnTop: true` no Electron/Windows fazem o DWM criar um handle de composição separado internamente. Sem o `AppUserModelID` fixado **antes** do ready e vinculado **diretamente à janela** via `setAppDetails`, o Windows registra os dois handles como janelas independentes — resultando em 2 entradas no Alt+Tab.

**Regras críticas:**
- `app.setAppUserModelId()` deve ficar **fora** do `whenReady()`, no topo do arquivo, antes de qualquer `app.commandLine`
- `win.setAppDetails({ appId: ... })` deve ser chamado **imediatamente** após o `new BrowserWindow()`, antes de qualquer outro método no `win`
- O `appId` deve ser **idêntico** nos dois lugares E igual ao `build.appId` do `package.json` (`com.sweeet.phoneproject`)
- `app.requestSingleInstanceLock()` deve estar logo após o `setAppUserModelId` — evita clonagem em cascata ao clicar em entradas fantasmas
- `app.on('browser-window-created')` deve setar `skipTaskbar(true)` em QUALQUER janela que não seja `win` — esta é a solução definitiva; sem ela, janelas internas do autoUpdater, DWM phantoms e captureWin aparecem no Alt+Tab
- `win.webContents.setWindowOpenHandler` deve retornar `{ action: 'deny' }` e redirecionar para `shell.openExternal` — sem isso `window.open()` cria BrowserWindows extras
- `skipTaskbar` da janela principal pode operar em 2 modos:
  - modo padrão: `false` (janela visível no Alt+Tab)
  - modo blindado anti-duplicata: `true` (janela fora do Alt+Tab), **desde que** exista saída explícita para o usuário (`Tray` com opção **Sair** e atalho de emergência `Ctrl+Shift+Q` com fallback)
- se tray + atalho global de saída falharem no runtime, o app deve fazer fallback automático para visível no Alt+Tab (segurança para não prender o cliente)

**Não remova** nenhum desses calls. O bug de janelas duplas já foi reproduzido múltiplas vezes.

---

## Regra geral para IAs

Ao pedir modificações, sempre especifique:
> "Não mexa nas flags de GPU do main.js", "Não remova o sistema de polling de atalhos", etc.

Ou simplesmente diga: **"respeite as regras do REGRAS.md"**.
