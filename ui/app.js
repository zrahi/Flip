const $ = (s) => document.querySelector(s);
const body = document.body;
const stage = $('#stage'), statusEl = $('#status');
const chatEl = $('#chat'), input = $('#input'), footer = $('footer');
const micBtn = $('#mic-btn'), sendBtn = $('#send-btn'), voiceBtn = $('#voice-btn'), muteBtn = $('#mute-btn');

const pet = new Pet(stage, $('#pet-host'));

let api = null;
let petName = 'Flip';
let chatId = null;
let chatHasMessages = false;
let busy = false;
let listening = false;
let voiceOn = false;
let muted = false;
let audioCtx = null;
let currentAudio = null;
let speakDone = null;
let levelTimer = 0;

const STATUS = {
  idle: 'vibing',
  excited: 'heyyy 👋',
  listening: 'listening… click the mic again when you\'re done',
  thinking: 'cooking up a reply…',
  working: 'working on it 🔧',
  talking: 'yapping',
  happy: 'LET\'S GOOO',
  sleeping: 'zzz… (poke me)',
};
const VOICE_STATUS = { listening: 'listening…', thinking: 'thinking…', working: 'working on it 🔧', talking: 'talking · tap me to cut me off' };
const POKES = ['ayo 😭', 'that tickles fr', 'bro I\'m tryna vibe', 'hehe', 'poke me again, I dare you', 'W poke ngl', 'hey!! 😤'];
const GREETINGS = ['yooo what\'s good 😤', 'ayy you\'re back!!', 'let\'s cook today fr', 'the GOAT has arrived 🐐'];
const pick = (a) => a[Math.floor(Math.random() * a.length)];

try { muted = localStorage.getItem('flip-muted') === '1'; } catch (e) {}
muteBtn.classList.toggle('muted', muted);

// ---------- pet ----------

let statusOverride = null;
pet.onchange = (state) => {
  statusEl.textContent = statusOverride || (voiceOn && VOICE_STATUS[state]) || STATUS[state] || '';
  statusOverride = null;
  if (api && state !== 'excited') api.pet_state(state);
};

function setState(state, text) {
  statusOverride = text || null;
  pet.set(state);
}

function flash(state, ms, text) {
  statusOverride = text || null;
  pet.flash(state, ms);
}

const calm = () => !busy && !listening && !voiceOn;

stage.addEventListener('mousemove', (e) => pet.lookAt(e.clientX, e.clientY));
stage.addEventListener('mouseleave', () => pet.lookAway());
pet.svg.addEventListener('mouseenter', () => { if (calm() && ['idle', 'sleeping'].includes(pet.state)) setState('excited'); });
pet.svg.addEventListener('mouseleave', () => { if (pet.state === 'excited') setState('idle'); });

pet.svg.addEventListener('click', () => {
  if (voiceOn && pet.state === 'talking') { stopSpeaking(); return; }  // cut him off
  if (!calm() || pet.state === 'talking') return;
  pet.poke();
  if (pet.state === 'sleeping') flash('happy', 1300, 'huh?? I\'m up I\'m up 😳');
  else setState('excited', pick(POKES));
});

// ---------- chat rendering ----------

function esc(s) {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function inline(t) {
  return esc(t)
    .replace(/`([^`\n]+)`/g, '<code class="inline">$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
    .replace(/\n/g, '<br>');
}

function format(text) {
  const parts = text.split(/```([\w+-]*)[^\S\n]*\n?([\s\S]*?)(?:```|$)/g);
  let html = '';
  for (let i = 0; i < parts.length; i += 3) {
    html += inline(parts[i].replace(/^\n+|\n+$/g, ''));
    if (i + 2 < parts.length) {
      html += `<div class="code"><div class="code-bar"><span>${esc(parts[i + 1] || 'code')}</span>` +
        `<button class="copy">copy</button></div><pre><code>${esc(parts[i + 2].replace(/\n$/, ''))}</code></pre></div>`;
    }
  }
  return html;
}

function addMsg(role, text, extra = '') {
  const row = document.createElement('div');
  row.className = `msg ${role} ${extra}`;
  if (role === 'pet') {
    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = petName;
    row.appendChild(who);
  }
  const b = document.createElement('div');
  b.className = 'b';
  b.innerHTML = format(text);
  row.appendChild(b);
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function addNote(text) {
  const n = document.createElement('div');
  n.className = 'note';
  n.textContent = text;
  chatEl.appendChild(n);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function showChat(chat) {
  chatId = chat.id;
  chatHasMessages = chat.messages.length > 0;
  chatEl.innerHTML = '';
  for (const m of chat.messages) addMsg(m.role === 'user' ? 'user' : 'pet', m.content);
  if (!chatHasMessages) addMsg('pet', `yooo I'm ${petName} 😤 type something, hit the mic, or tap the voice button to call me`);
}

chatEl.addEventListener('click', async (e) => {
  const btn = e.target.closest('.copy');
  if (!btn) return;
  const code = btn.closest('.code').querySelector('code').textContent;
  try {
    await navigator.clipboard.writeText(code);
  } catch (err) {
    const t = document.createElement('textarea');
    t.value = code;
    document.body.appendChild(t);
    t.select();
    document.execCommand('copy');
    t.remove();
  }
  btn.textContent = 'copied ✓';
  setTimeout(() => { btn.textContent = 'copy'; }, 1500);
});

// Called from Python when he uses a tool (memory, Roblox Studio…).
window.onTool = (name) => {
  if (name === 'remember') { addNote('🧠 saved to memory'); return; }
  if (name === 'forget') { addNote('🧠 forgot something'); return; }
  setState('working');
  addNote(`🔧 ${name.replace(/_/g, ' ')}`);
};

// ---------- sending ----------

function setBusy(b) {
  busy = b;
  sendBtn.disabled = b;
  voiceBtn.disabled = b;
  micBtn.disabled = b && !listening;
}

async function send(text) {
  text = (text || '').trim();
  if (!text || busy || !api) return;
  pet.wake();
  stopSpeaking();
  addMsg('user', text);
  if (voiceOn) { $('#cap-you').textContent = `“${text}”`; $('#cap-pet').textContent = ''; }
  input.value = '';
  autosize();
  setBusy(true);
  setState('thinking');

  let res;
  try { res = await api.send(chatId, text, voiceOn); } catch (e) { res = { error: `something broke 😭 (${e})` }; }

  if (res.error) {
    setBusy(false);
    addMsg('pet', res.error, 'error');
    if (voiceOn) $('#cap-pet').textContent = res.error;
    setState('idle', 'uh oh 😵');
    return;
  }

  addMsg('pet', res.reply);
  if (voiceOn) $('#cap-pet').textContent = res.reply;
  if (!chatHasMessages) { chatHasMessages = true; refreshChatList(); }
  if (!muted || voiceOn) {
    if (!voiceOn) statusEl.textContent = 'warming up the vocals…';
    await speak(res.reply);
  }
  setBusy(false);
  if (!voiceOn && /let'?s go|🔥|goated|\bW\b|hype|🐐|💪|🎉/i.test(res.reply)) flash('happy', 1300);
  else setState('idle');
}

// ---------- voice out ----------

function stopSpeaking() {
  if (currentAudio) currentAudio.pause();
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (speakDone) speakDone();
}

async function speak(text) {
  let mp3 = null;
  try { mp3 = await api.speak(text); } catch (e) {}
  if (mp3) return playMp3(mp3, text);
  return speakWithWindows(text);
}

function playMp3(b64, text) {
  return new Promise((resolve) => {
    const audio = new Audio(`data:audio/mpeg;base64,${b64}`);
    currentAudio = audio;
    let analyser = null, data = null, raf = 0, finished = false;

    try {
      audioCtx = audioCtx || new AudioContext();
      const src = audioCtx.createMediaElementSource(audio);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      data = new Uint8Array(analyser.fftSize);
      src.connect(analyser);
      analyser.connect(audioCtx.destination);
      audioCtx.resume();
    } catch (e) { analyser = null; }

    // Move his mouth with how loud the voice is right now.
    const tick = () => {
      let level;
      if (analyser) {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) { const d = (v - 128) / 128; sum += d * d; }
        level = Math.min(1, Math.sqrt(sum / data.length) * 4.5);
      } else {
        level = 0.3 + Math.random() * 0.6;
      }
      pet.mouth(level);
      raf = requestAnimationFrame(tick);
    };

    const done = () => {
      if (finished) return;
      finished = true;
      cancelAnimationFrame(raf);
      pet.mouth(0);
      currentAudio = null;
      speakDone = null;
      resolve();
    };
    speakDone = done;
    audio.onended = done;
    audio.onpause = done;
    audio.onerror = done;

    audio.play()
      .then(() => { setState('talking'); tick(); })
      .catch(() => { finished = true; currentAudio = null; speakWithWindows(text).then(resolve); });
  });
}

// Backup voice (Windows' built-in one) for when the online voice doesn't work.
function speakWithWindows(text) {
  return new Promise((resolve) => {
    if (!window.speechSynthesis) return resolve();
    const clean = text.replace(/```[\s\S]*?(```|$)/g, ' I dropped the code in the chat. ')
      .replace(/https?:\/\/\S+/g, ' the link ')
      .replace(/[`*_#>|]/g, '')
      .replace(/\p{Extended_Pictographic}/gu, '')
      .slice(0, 700);
    const u = new SpeechSynthesisUtterance(clean);
    const voices = speechSynthesis.getVoices();
    u.voice = voices.find((v) => /Guy|Andrew|Brian|Christopher|Mark|David|Male/i.test(v.name) && /^en/i.test(v.lang)) || null;
    u.rate = 1.1;
    let timer = 0;
    const done = () => { clearInterval(timer); pet.mouth(0); speakDone = null; resolve(); };
    speakDone = () => { speechSynthesis.cancel(); done(); };
    u.onstart = () => {
      setState('talking');
      timer = setInterval(() => pet.mouth(0.2 + Math.random() * 0.8), 90);
    };
    u.onend = done;
    u.onerror = done;
    speechSynthesis.speak(u);
  });
}

// ---------- voice in: click-to-talk ----------

async function toggleMic() {
  if (!api || (busy && !listening) || voiceOn) return;
  pet.wake();
  if (!listening) {
    stopSpeaking();
    const r = await api.listen_start();
    if (r.error) { addMsg('pet', r.error, 'error'); return; }
    listening = true;
    micBtn.classList.add('on');
    setBusy(true);
    setState('listening');
    pollLevel(true);
  } else {
    listening = false;
    pollLevel(false);
    micBtn.classList.remove('on');
    setState('thinking', 'turning your words into text…');
    const r = await api.listen_stop();
    setBusy(false);
    if (r.error) { addMsg('pet', r.error, 'error'); setState('idle'); return; }
    if (!r.text) { setState('idle', 'didn\'t catch that 👂 try again?'); return; }
    await send(r.text);
  }
}

// ---------- voice chat mode (like a phone call) ----------

function pollLevel(on) {
  clearInterval(levelTimer);
  pet.level(0);
  if (on) levelTimer = setInterval(async () => { try { pet.level(await api.mic_level()); } catch (e) {} }, 100);
}

async function startVoice() {
  if (!api || busy || voiceOn) return;
  closeAll();
  voiceOn = true;
  body.classList.add('voice');
  $('#cap-you').textContent = '';
  $('#cap-pet').textContent = pick(['yo, I\'m listening 👂', 'talk to me bro', 'what\'s good? I\'m all ears']);
  pet.wake();
  while (voiceOn) {
    setState('listening');
    pollLevel(true);
    const r = await api.voice_listen();
    pollLevel(false);
    if (!voiceOn || r.ended) break;
    if (r.error) { $('#cap-pet').textContent = r.error; addMsg('pet', r.error, 'error'); break; }
    if (r.text) await send(r.text);
  }
  endVoice();
}

function endVoice() {
  if (!voiceOn) return;
  voiceOn = false;
  pollLevel(false);
  api.voice_cancel();
  stopSpeaking();
  body.classList.remove('voice');
  if (!busy) setState('idle');
}

// ---------- input ----------

function autosize() {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  footer.classList.toggle('has-text', input.value.trim().length > 0);
}

input.addEventListener('input', () => { autosize(); pet.wake(); });
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send(input.value);
  }
});
sendBtn.addEventListener('click', () => send(input.value));
micBtn.addEventListener('click', toggleMic);
voiceBtn.addEventListener('click', startVoice);
$('#end-voice').addEventListener('click', endVoice);
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (voiceOn) endVoice();
  else closeAll();
});

muteBtn.addEventListener('click', () => {
  muted = !muted;
  muteBtn.classList.toggle('muted', muted);
  if (muted) stopSpeaking();
  try { localStorage.setItem('flip-muted', muted ? '1' : '0'); } catch (e) {}
  if (calm()) setState('idle', muted ? 'ok ok I\'ll stay quiet 🤐' : 'voice back on 🗣️');
});

$('#reset-btn').title = 'New chat';
$('#reset-btn').addEventListener('click', newChat);

// ---------- chats drawer ----------

function closeAll() {
  body.classList.remove('drawer-open', 'panel-open');
}

async function refreshChatList() {
  const chats = await api.list_chats();
  const list = $('#chat-list');
  list.innerHTML = '';
  if (!chats.length) list.innerHTML = '<div class="empty">no chats yet</div>';
  for (const c of chats) {
    const item = document.createElement('div');
    item.className = 'chat-item' + (c.id === chatId ? ' current' : '');
    item.innerHTML = `<span class="t"></span><button class="del" title="Delete chat">🗑</button>`;
    item.querySelector('.t').textContent = c.title;
    item.addEventListener('click', async (e) => {
      if (e.target.closest('.del')) {
        await api.delete_chat(c.id);
        if (c.id === chatId) showChat(await api.new_chat());
        refreshChatList();
        return;
      }
      if (busy) return;
      showChat(await api.open_chat_id(c.id));
      closeAll();
    });
    list.appendChild(item);
  }
}

async function newChat() {
  if (busy || !api) return;
  closeAll();
  if (chatHasMessages) showChat(await api.new_chat());
  flash('happy', 1300, 'fresh chat, who dis 😎');
}

$('#menu-btn').addEventListener('click', () => {
  if (voiceOn) return;
  refreshChatList();
  body.classList.add('drawer-open');
});
$('#scrim').addEventListener('click', closeAll);
$('#new-chat').addEventListener('click', newChat);

// ---------- memory + settings ----------

function openPanel(which) {
  body.classList.remove('drawer-open');
  $('#panel').dataset.show = which;
  $('#panel-title').textContent = which === 'memory' ? '🧠 What I remember' : '⚙️ Settings';
  body.classList.add('panel-open');
}
$('#panel-close').addEventListener('click', closeAll);

function renderMemories(mems) {
  const list = $('#mem-list');
  list.innerHTML = '';
  if (!mems.length) list.innerHTML = '<div class="empty">nothing yet, tell me about yourself 👀</div>';
  for (const m of mems.slice().reverse()) {
    const row = document.createElement('div');
    row.className = 'mem';
    row.innerHTML = '<span></span><button title="Forget this">✕</button>';
    row.querySelector('span').textContent = m.text;
    row.querySelector('button').addEventListener('click', async () => renderMemories(await api.forget(m.id)));
    list.appendChild(row);
  }
}

$('#memory-btn').addEventListener('click', async () => {
  openPanel('memory');
  renderMemories(await api.memories());
});
async function addMemory() {
  const v = $('#mem-input').value.trim();
  if (!v) return;
  $('#mem-input').value = '';
  renderMemories(await api.remember(v));
}
$('#mem-add').addEventListener('click', addMemory);
$('#mem-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') addMemory(); });

$('#settings-btn').addEventListener('click', async () => {
  const s = await api.get_settings();
  $('#set-name').value = s.name;
  $('#set-voice').value = s.voice;
  $('#set-roblox').checked = !!s.roblox_studio;
  $('#set-note').textContent = '';
  openPanel('settings');
});
$('#set-save').addEventListener('click', async () => {
  await api.save_settings({
    name: $('#set-name').value.trim() || 'Flip',
    voice: $('#set-voice').value,
    roblox_studio: $('#set-roblox').checked,
  });
  $('#set-note').textContent = 'saved ✓ close and reopen me to apply everything 🔁';
});
$('#set-folder').addEventListener('click', () => api.open_folder());

// ---------- desktop pet ----------

window.onPetChanged = (visible) => $('#desk-btn').classList.toggle('active', visible);
$('#desk-btn').addEventListener('click', async () => {
  const visible = await api.pet_visible();
  if (visible) await api.hide_pet();
  else await api.show_pet();
  onPetChanged(!visible);
  if (!visible) flash('happy', 1300, 'I\'m on your desktop now 😎 close this window and I\'ll stay');
});

// ---------- first-run brain setup ----------

async function watchBrain() {
  let s;
  try { s = await api.brain_status(); } catch (e) { setTimeout(watchBrain, 1000); return; }
  if (s.state === 'ready') {
    if (body.classList.contains('setup')) {
      body.classList.remove('setup', 'setup-error');
      flash('happy', 1400, 'brain loaded, let\'s cook 🧠🔥');
    }
    return;
  }
  body.classList.add('setup');
  body.classList.toggle('setup-error', s.state === 'error');
  $('#setup-title').textContent = s.title;
  $('#setup-detail').textContent = s.detail || '';
  const bar = $('#setup-bar');
  bar.classList.toggle('pulse', s.progress == null && s.state !== 'error');
  bar.style.width = s.progress == null ? '' : `${Math.round(s.progress * 100)}%`;
  $('#setup-retry').hidden = s.state !== 'error';
  $('#setup-note').hidden = s.state === 'error';
  if (pet.state !== 'working' && s.state !== 'error') setState('working', ' ');
  statusEl.textContent = s.state === 'error' ? 'uh oh 😵' : 'setting up…';
  if (s.state !== 'error') setTimeout(watchBrain, 500);
}
$('#setup-retry').addEventListener('click', async () => {
  $('#setup-retry').hidden = true;
  await api.retry_brain();
  setTimeout(watchBrain, 300);
});

// ---------- startup ----------

async function pollRoblox() {
  let s;
  try { s = await api.status(); } catch (e) { return; }
  const dot = $('#roblox-dot');
  const state = s.roblox;
  dot.className = 'dot' + (state === 'connected' ? ' on' : state.startsWith('error') ? ' err' : '');
  dot.title = `Roblox Studio: ${state}`;
  dot.hidden = state === 'off';
  if (state === 'starting') setTimeout(pollRoblox, 2000);
}

window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  const info = await api.hello();
  petName = info.name;
  document.title = petName;
  $('#pet-name').textContent = petName;
  pet.svg.setAttribute('aria-label', petName);
  input.placeholder = `talk to ${petName}…`;
  onPetChanged(info.pet);
  showChat(info.chat);
  flash('happy', 1300, pick(GREETINGS));
  watchBrain();
  pollRoblox();
});

autosize();
