const $ = (s) => document.querySelector(s);
const body = document.body;
const stage = $('#stage'), statusEl = $('#status');
const chatEl = $('#chat'), thread = $('#thread'), input = $('#input'), footer = $('footer');
const micBtn = $('#mic-btn'), sendBtn = $('#send-btn'), voiceBtn = $('#voice-btn'), muteBtn = $('#mute-btn');

const pet = new Pet(stage, $('#pet-host'));

let api = null;
let petName = 'Flip';
let me = null;               // the profile that's chatting
let chatId = null;
let chatTitle = 'New chat';
let allChats = [];
let busy = false;
let listening = false;
let voiceOn = false;
let muted = false;
let fast = false;
let audioCtx = null;
let currentAudio = null;
let speakDone = null;
let levelTimer = 0;
let stream = null;           // the reply that's being written right now: {b, text}

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
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const local = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
};

muted = local.get('flip-muted') === '1';
muteBtn.classList.toggle('muted', muted);
if (local.get('flip-sidebar') === 'closed') body.classList.add('sb-collapsed');

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

// ---------- message rendering ----------

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

const nearBottom = () => chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight < 80;
const toBottom = () => { chatEl.scrollTop = chatEl.scrollHeight; };

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
  thread.appendChild(row);
  toBottom();
  return row;
}

function addNote(text) {
  const n = document.createElement('div');
  n.className = 'note';
  n.textContent = text;
  thread.appendChild(n);
  toBottom();
}

function setChatting(on) {
  body.classList.toggle('chatting', on);
}

function setTitle(title) {
  chatTitle = title || 'New chat';
  $('#chat-title').textContent = chatTitle;
  document.title = chatTitle === 'New chat' ? petName : `${chatTitle} · ${petName}`;
}

function showChat(chat) {
  chatId = chat.id;
  setTitle(chat.messages.length ? chat.title : 'New chat');
  thread.innerHTML = '';
  for (const m of chat.messages) addMsg(m.role === 'user' ? 'user' : 'pet', m.content);
  setChatting(chat.messages.length > 0);
  $('#empty-title').textContent = me ? `what's good, ${me.name}? 👋` : 'what\'s good? 👋';
  renderChatList();
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

// Called from Python while he writes: shows the reply word by word.
window.onText = (piece) => {
  if (!stream) return;
  const stick = nearBottom();
  stream.text += piece;
  stream.b.innerHTML = format(stream.text);
  if (pet.state !== 'working') setState('thinking', 'typing…');
  if (stick) toBottom();
};

// Called from Python when he throws away a reply that repeated an earlier one and tries again.
window.onResetText = () => {
  if (!stream) return;
  stream.text = '';
  stream.b.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
};

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
  body.classList.toggle('busy', b);
  micBtn.disabled = b && !listening;
}

async function send(text) {
  text = (text || '').trim();
  if (!text || busy || !api) return;
  pet.wake();
  stopSpeaking();
  setChatting(true);
  addMsg('user', text);
  if (voiceOn) { $('#cap-you').textContent = `“${text}”`; $('#cap-pet').textContent = ''; }
  input.value = '';
  autosize();
  setBusy(true);
  setState('thinking');

  const row = addMsg('pet', '');
  const b = row.querySelector('.b');
  b.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
  stream = { b, text: '' };

  let res;
  try { res = await api.send(chatId, text, voiceOn); } catch (e) { res = { error: `something broke 😭 (${e})` }; }
  stream = null;

  if (res.error) {
    setBusy(false);
    row.classList.add('error');
    b.innerHTML = format(res.error);
    if (voiceOn) $('#cap-pet').textContent = res.error;
    setState('idle', 'uh oh 😵');
    return;
  }

  b.innerHTML = format(res.reply);
  if (res.stopped) row.insertAdjacentHTML('beforeend', '<div class="stopped">stopped</div>');
  else if (res.secs != null) row.insertAdjacentHTML('beforeend', `<div class="meta">${res.secs}s${fast ? ' · ⚡ fast' : ''}</div>`);
  if (voiceOn) $('#cap-pet').textContent = res.reply;
  if (chatTitle === 'New chat' || !allChats.some((c) => c.id === chatId)) {
    setTitle(res.title);
    refreshChatList();
  }
  if (!res.stopped && (!muted || voiceOn)) {
    if (!voiceOn) statusEl.textContent = 'warming up the vocals…';
    await speak(res.reply);
  }
  setBusy(false);
  if (!voiceOn && !res.stopped && /let'?s go|🔥|goated|\bW\b|hype|🐐|💪|🎉/i.test(res.reply)) flash('happy', 1300);
  else setState('idle');
}

function stopReply() {
  if (!api) return;
  api.stop();
  stopSpeaking();
}

// ---------- voice out ----------

function stopSpeaking() {
  speakToken = null;
  if (currentAudio) currentAudio.pause();
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (speakDone) speakDone();
}
window.stopSpeaking = stopSpeaking;

let speakToken = null;

// Speaks a reply sentence by sentence: the next sentence gets made while the current one plays.
async function speak(text) {
  let parts = [];
  try { parts = await api.speech_parts(text); } catch (e) {}
  if (!parts.length) return;
  const token = {};
  speakToken = token;
  let next = api.say(parts[0]);
  for (let i = 0; i < parts.length; i++) {
    let clip = null;
    try { clip = await next; } catch (e) {}
    if (speakToken !== token) return;
    next = i + 1 < parts.length ? api.say(parts[i + 1]) : null;
    if (clip) await playClip(clip);
    else await speakWithWindows(parts[i]);
    if (speakToken !== token) return;
  }
  speakToken = null;
}

function playClip(clip) {
  return new Promise((resolve) => {
    const audio = new Audio(`data:${clip.mime};base64,${clip.audio}`);
    audio.preservesPitch = false;          // playing a bit faster makes him sound younger (cute style)
    audio.playbackRate = clip.rate || 1;
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
      .catch(() => { finished = true; currentAudio = null; resolve(); });
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
    u.pitch = 1.6;  // he's small, so he sounds small
    let timer = 0;
    let over = false;
    const done = () => { if (over) return; over = true; clearInterval(timer); pet.mouth(0); speakDone = null; resolve(); };
    speakDone = () => { speechSynthesis.cancel(); done(); };
    u.onstart = () => {
      setState('talking');
      timer = setInterval(() => pet.mouth(0.2 + Math.random() * 0.8), 90);
    };
    u.onend = done;
    u.onerror = done;
    setTimeout(done, clean.length * 90 + 4000);  // in case Windows never says it's finished
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
    if (r.error) { setChatting(true); addMsg('pet', r.error, 'error'); return; }
    listening = true;
    micBtn.classList.add('on');
    setBusy(true);
    body.classList.remove('busy');  // no stop button while recording, the mic button stops it
    setState('listening');
    pollLevel(true);
  } else {
    listening = false;
    pollLevel(false);
    micBtn.classList.remove('on');
    setState('thinking', 'turning your words into text…');
    const r = await api.listen_stop();
    setBusy(false);
    if (r.error) { setChatting(true); addMsg('pet', r.error, 'error'); setState('idle'); return; }
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
  if (!api || busy || voiceOn || !me) return;
  closeAll();
  voiceOn = true;
  api.voice_state(true);
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
    if (r.error) { $('#cap-pet').textContent = r.error; setChatting(true); addMsg('pet', r.error, 'error'); break; }
    if (r.text) await send(r.text);
  }
  endVoice();
}

function endVoice() {
  if (!voiceOn) return;
  voiceOn = false;
  api.voice_state(false);
  pollLevel(false);
  api.voice_cancel();
  if (busy) api.stop();
  stopSpeaking();
  body.classList.remove('voice');
  if (!busy) setState('idle');
}

// The voice button on the desktop pet.
window.toggleVoiceFromPet = () => { if (voiceOn) endVoice(); else startVoice(); };

// ---------- composer ----------

function autosize() {
  input.style.height = 'auto';
  const h = Math.min(input.scrollHeight, 180);
  input.style.height = `${h}px`;
  input.style.overflowY = input.scrollHeight > 180 ? 'auto' : 'hidden';
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
$('#stop-btn').addEventListener('click', stopReply);
micBtn.addEventListener('click', toggleMic);
voiceBtn.addEventListener('click', startVoice);
$('#end-voice').addEventListener('click', endVoice);
for (const chip of document.querySelectorAll('.chip-btn')) {
  chip.addEventListener('click', () => send(chip.textContent.replace(/^\P{L}+/u, '')));
}
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (voiceOn) endVoice();
  else if (busy && !listening) stopReply();
  else closeAll();
});

muteBtn.addEventListener('click', () => {
  muted = !muted;
  muteBtn.classList.toggle('muted', muted);
  if (muted) stopSpeaking();
  local.set('flip-muted', muted ? '1' : '0');
  if (calm()) setState('idle', muted ? 'ok ok I\'ll stay quiet 🤐' : 'voice back on 🗣️');
});

// ---------- sidebar: chats ----------

const narrow = () => window.matchMedia('(max-width: 820px)').matches;

function closeAll() {
  body.classList.remove('sb-open', 'panel-open');
  $('#me-menu').hidden = true;
}

function toggleSidebar(open) {
  if (narrow()) {
    body.classList.toggle('sb-open', open);
  } else {
    body.classList.toggle('sb-collapsed', !open);
    local.set('flip-sidebar', open ? 'open' : 'closed');
  }
}
$('#sb-open').addEventListener('click', () => { refreshChatList(); toggleSidebar(true); });
$('#sb-close').addEventListener('click', () => toggleSidebar(false));
$('#scrim').addEventListener('click', closeAll);

async function refreshChatList() {
  if (!api || !me) return;
  allChats = await api.list_chats();
  renderChatList();
}

function renderChatList() {
  const q = $('#chat-search').value.trim().toLowerCase();
  const chats = allChats.filter((c) => !q || c.title.toLowerCase().includes(q));
  const pinned = chats.filter((c) => c.pinned), rest = chats.filter((c) => !c.pinned);
  $('#pinned-sec').hidden = !pinned.length;
  fillList($('#pinned-list'), pinned);
  fillList($('#chat-list'), rest);
  if (!rest.length) $('#chat-list').innerHTML = `<div class="empty-list">${q ? 'no chats match' : 'no chats yet'}</div>`;
}

function fillList(list, chats) {
  list.innerHTML = '';
  for (const c of chats) {
    const item = document.createElement('div');
    item.className = 'chat-item' + (c.id === chatId ? ' current' : '');
    item.innerHTML = '<span class="t"></span><span class="acts">' +
      `<button data-a="pin" title="${c.pinned ? 'Unpin' : 'Pin'}">${c.pinned ? '📍' : '📌'}</button>` +
      '<button data-a="rename" title="Rename">✏️</button><button data-a="delete" title="Delete">🗑</button></span>';
    item.querySelector('.t').textContent = c.title;
    item.addEventListener('click', (e) => chatItemClick(e, c, item));
    list.appendChild(item);
  }
}

async function chatItemClick(e, c, item) {
  const act = e.target.closest('button')?.dataset.a;
  if (act === 'pin') { allChats = await api.pin_chat(c.id, !c.pinned); renderChatList(); return; }
  if (act === 'delete') {
    allChats = await api.delete_chat(c.id);
    if (c.id === chatId) showChat(await api.new_chat());
    else renderChatList();
    return;
  }
  if (act === 'rename') { renameInList(c, item); return; }
  if (e.target.tagName === 'INPUT' || busy || voiceOn) return;
  showChat(await api.open_chat_id(c.id));
  if (narrow()) closeAll();
}

function renameInList(c, item) {
  const box = document.createElement('input');
  box.value = c.title;
  box.maxLength = 60;
  item.querySelector('.t').replaceWith(box);
  box.focus();
  box.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    if (save && box.value.trim()) {
      allChats = await api.rename_chat(c.id, box.value.trim());
      if (c.id === chatId) setTitle(box.value.trim());
    }
    renderChatList();
  };
  box.addEventListener('keydown', (e) => { if (e.key === 'Enter') finish(true); if (e.key === 'Escape') finish(false); });
  box.addEventListener('blur', () => finish(true));
}

$('#chat-search').addEventListener('input', renderChatList);

async function newChat() {
  if (!api || !me) return;
  if (busy) stopReply();
  if (voiceOn) endVoice();
  showChat(await api.new_chat());
  input.value = '';
  autosize();
  input.focus();
  if (narrow()) closeAll();
  setState('idle', 'fresh chat, who dis 😎');
}
$('#new-chat').addEventListener('click', newChat);
$('#reset-btn').addEventListener('click', newChat);

// Rename the current chat by clicking its title.
$('#chat-title').addEventListener('click', () => {
  if (!allChats.some((c) => c.id === chatId)) return;  // nothing to rename until the chat has a message
  const box = $('#title-edit');
  box.value = chatTitle;
  box.hidden = false;
  $('#chat-title').hidden = true;
  box.focus();
  box.select();
});
async function finishTitle(save) {
  const box = $('#title-edit');
  if (box.hidden) return;
  box.hidden = true;
  $('#chat-title').hidden = false;
  if (save && box.value.trim() && box.value.trim() !== chatTitle) {
    setTitle(box.value.trim());
    allChats = await api.rename_chat(chatId, box.value.trim());
    renderChatList();
  }
}
$('#title-edit').addEventListener('keydown', (e) => { if (e.key === 'Enter') finishTitle(true); if (e.key === 'Escape') finishTitle(false); });
$('#title-edit').addEventListener('blur', () => finishTitle(true));

// ---------- sidebar: profile menu, memory, settings ----------

$('#me-btn').addEventListener('click', () => { $('#me-menu').hidden = !$('#me-menu').hidden; });
$('#me-menu').addEventListener('click', (e) => {
  const act = e.target.closest('button')?.dataset.act;
  $('#me-menu').hidden = true;
  if (act === 'memory') openMemory();
  if (act === 'settings') openSettings();
  if (act === 'switch') switchProfile();
  if (act === 'logout') logOut();
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('.sb-foot')) $('#me-menu').hidden = true;
});

function openPanel(which) {
  body.classList.remove('sb-open');
  $('#panel').dataset.show = which;
  $('#panel-title').textContent = { memory: '🧠 What I remember', settings: '⚙️ Settings', update: '⬆ New update',
    share: '👀 Share your screen' }[which];
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

async function openMemory() {
  openPanel('memory');
  renderMemories(await api.memories());
}
async function addMemory() {
  const v = $('#mem-input').value.trim();
  if (!v) return;
  $('#mem-input').value = '';
  renderMemories(await api.remember(v));
}
$('#mem-add').addEventListener('click', addMemory);
$('#mem-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') addMemory(); });

async function openSettings() {
  const s = await api.get_settings();
  $('#set-name').value = s.name;
  $('#set-voice').innerHTML = Object.entries(s.voices).map(([id, label]) => `<option value="${id}">${esc(label)}</option>`).join('');
  $('#set-voice').value = s.voices[s.voice] ? s.voice : Object.keys(s.voices)[0];
  $('#set-style').value = s.voice_style || 'cute';
  $('#set-speed').value = String(s.talk_speed || 1);
  $('#set-mic').innerHTML = '<option value="">Windows default</option>' +
    s.mics.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join('');
  $('#set-mic').value = s.mic == null ? '' : String(s.mic);
  $('#set-roblox').checked = !!s.roblox_studio;
  $('#set-note').textContent = '';
  $('#pw-note').textContent = '';
  $('#clean-note').textContent = '';
  $('#update-status').textContent = update ? `version ${update.current}` : '';
  api.storage_report().then(renderStorage);
  const b = await api.brain_status();
  $('#brain-info').textContent = b.model
    ? `brain: ${b.model}${b.fast ? ' (fast mode)' : ''}${b.hardware ? ` · running on ${b.hardware}` : ''}` : '';
  openPanel('settings');
}
$('#set-save').addEventListener('click', async () => {
  await api.save_settings(currentSettings());
  $('#set-note').textContent = 'saved ✓ voice changes work right away, the rest after you reopen me 🔁';
});
$('#set-folder').addEventListener('click', () => api.open_folder());

function currentSettings() {
  const mic = $('#set-mic').value;
  return {
    name: $('#set-name').value.trim() || 'Flip',
    voice: $('#set-voice').value,
    voice_style: $('#set-style').value,
    talk_speed: parseFloat($('#set-speed').value),
    mic: mic === '' ? null : parseInt(mic, 10),
    roblox_studio: $('#set-roblox').checked,
  };
}
$('#voice-test').addEventListener('click', async () => {
  await api.save_settings(currentSettings());  // voice settings apply right away
  stopSpeaking();
  speak(pick(['yo, it\'s me. how do I sound?', 'this is my voice, lowkey fire right?', 'testing, testing. I\'m ready to clutch.']));
});

// ---------- storage ----------

function renderStorage(r) {
  $('#storage-total').textContent = `${r.total_gb} GB total`;
  const list = $('#storage-list');
  list.innerHTML = '';
  for (const it of r.items) {
    const row = document.createElement('div');
    row.className = 'st-row' + (it.in_use ? '' : ' unused');
    row.innerHTML = '<span><span class="w"></span><span class="tag"></span></span><span class="gb"></span>';
    row.querySelector('.w').textContent = it.what;
    row.querySelector('.tag').textContent = it.in_use ? 'in use' : '';
    row.querySelector('.gb').textContent = it.gb >= 0.1 ? `${it.gb} GB` : '< 0.1 GB';
    list.appendChild(row);
  }
  $('#clean-btn').textContent = r.freeable_gb > 0 ? `🧹 Clean up (frees ${r.freeable_gb} GB)` : '🧹 Clean up';
}

$('#clean-btn').addEventListener('click', async () => {
  $('#clean-btn').disabled = true;
  $('#clean-note').textContent = 'cleaning…';
  const r = await api.clean_up();
  $('#clean-btn').disabled = false;
  $('#clean-note').textContent = r.freed_gb > 0 ? `freed ${r.freed_gb} GB 🧹✨` : 'already squeaky clean ✨';
  renderStorage(r.report);
});

$('#delete-all').addEventListener('click', async () => {
  const app = $('#del-app').checked;
  if (!confirm(`Delete ALL of Flip's stuff on this PC?\n\nHis brains, every account, profile, chat and memory${app ? ', and Flip.exe itself' : ''}. This can't be undone.`)) return;
  if (!confirm('Last chance: really delete everything? 😢')) return;
  setState('sleeping', 'bye bye 👋');
  await api.delete_everything(app);
});
$('#pw-save').addEventListener('click', async () => {
  const r = await api.change_password($('#pw-old').value, $('#pw-new').value);
  $('#pw-note').textContent = r.error || 'password changed ✓';
  if (!r.error) { $('#pw-old').value = ''; $('#pw-new').value = ''; }
});

// ---------- fast mode ----------

function showVision(on) {
  $('#share-btn').hidden = !on;
  $('#share-voice').hidden = !on;
}

function showFast(on, s = {}) {
  fast = !!on;
  $('#fast-btn').classList.toggle('on', fast);
  const info = s.model ? `\nbrain: ${s.model}${s.hardware ? ` on ${s.hardware}` : ''}` : '';
  $('#fast-btn').title = (fast ? 'Fast mode is on: quicker, a bit less smart. Click for smart mode.'
    : 'Fast mode: a smaller brain that answers way quicker') + info;
}
$('#fast-btn').addEventListener('click', async () => {
  if (busy || voiceOn) return;
  const s = await api.set_fast(!fast);
  showFast(s.fast);
  watchBrain();
});

// ---------- desktop pet ----------

window.onPetChanged = (visible) => $('#desk-btn').classList.toggle('active', visible);
$('#desk-btn').addEventListener('click', async () => {
  const visible = await api.pet_visible();
  if (visible) await api.hide_pet();
  else await api.show_pet();
  onPetChanged(!visible);
  if (!visible) flash('happy', 1300, 'I\'m on your desktop now 😎 close this window and I\'ll stay');
});

// ---------- brain setup ----------

async function watchBrain() {
  let s;
  try { s = await api.brain_status(); } catch (e) { setTimeout(watchBrain, 1000); return; }
  if ('fast' in s) showFast(s.fast, s);
  showVision(!!s.vision);
  if (s.state === 'ready') {
    if (body.classList.contains('setup')) {
      body.classList.remove('setup', 'setup-error');
      const cpu = /^CPU/.test(s.hardware || '');
      flash('happy', 2500, cpu ? 'brain loaded, but only on your processor 🐢 replies will be slower'
        : fast ? 'fast mode on ⚡ let\'s go' : 'brain loaded, let\'s cook 🧠🔥');
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
  $('#setup-note').hidden = s.state === 'error' || s.state === 'loading';
  if (pet.state !== 'working' && s.state !== 'error') setState('working', ' ');
  statusEl.textContent = s.state === 'error' ? 'uh oh 😵' : 'setting up…';
  if (s.state !== 'error') setTimeout(watchBrain, 500);
}
$('#setup-retry').addEventListener('click', async () => {
  $('#setup-retry').hidden = true;
  await api.retry_brain();
  setTimeout(watchBrain, 300);
});

// ---------- log in / create account ----------

let authMode = 'login';

function showAuth(mode = 'login') {
  authMode = mode;
  body.classList.add('auth');
  body.classList.remove('profiles');
  $('#tab-login').classList.toggle('on', mode === 'login');
  $('#tab-signup').classList.toggle('on', mode === 'signup');
  $('#auth-pass2').hidden = mode === 'login';
  $('#auth-go').textContent = mode === 'login' ? 'log in' : 'create account';
  $('#auth-error').textContent = '';
  $('#auth-note').textContent = mode === 'signup'
    ? 'no email needed. your password gets scrambled before it\'s saved, and there\'s no reset, so don\'t forget it 🔐'
    : '';
  $('#auth-pass').value = '';
  $('#auth-pass2').value = '';
  $('#auth-user').focus();
}

async function submitAuth() {
  const user = $('#auth-user').value.trim(), pass = $('#auth-pass').value, remember = $('#auth-remember').checked;
  if (!user || !pass) { $('#auth-error').textContent = 'fill in your username and password'; return; }
  if (authMode === 'signup' && pass !== $('#auth-pass2').value) { $('#auth-error').textContent = 'passwords don\'t match'; return; }
  $('#auth-go').disabled = true;
  const r = authMode === 'login' ? await api.login(user, pass, remember) : await api.create_account(user, pass, remember);
  $('#auth-go').disabled = false;
  if (r.error) { $('#auth-error').textContent = r.error; $('#auth-pass').value = ''; return; }
  body.classList.remove('auth');
  openAccount(r.account);
}

function openAccount(acct) {
  $('#acct-name').textContent = `@${acct.username}`;
  $('#me-acct').textContent = `@${acct.username}`;
  const only = acct.profiles.length === 1 && !acct.profiles[0].has_pin ? acct.profiles[0] : null;
  if (only) api.enter_profile(only.id, '').then(enterWith);
  else showProfiles(acct.profiles);
}

async function logOut() {
  closeAll();
  if (sharing) stopShare();
  if (voiceOn) endVoice();
  if (busy) stopReply();
  await api.log_out();
  me = null;
  thread.innerHTML = '';
  allChats = [];
  showAuth('login');
}

$('#tab-login').addEventListener('click', () => showAuth('login'));
$('#tab-signup').addEventListener('click', () => showAuth('signup'));
$('#auth-go').addEventListener('click', submitAuth);
for (const id of ['#auth-user', '#auth-pass', '#auth-pass2']) {
  $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter') submitAuth(); });
}
$('#pw-eye').addEventListener('click', () => {
  const show = $('#auth-pass').type === 'password';
  $('#auth-pass').type = $('#auth-pass2').type = show ? 'text' : 'password';
  $('#pw-eye').textContent = show ? 'hide' : 'show';
});
$('#log-out').addEventListener('click', logOut);

// ---------- profiles ----------

let profiles = [];
let pinFor = null;

function showProfiles(list) {
  profiles = list;
  body.classList.remove('auth');
  body.classList.add('profiles');
  body.classList.remove('picking', 'manage');
  $('#prof-manage').textContent = 'manage profiles';
  $('#prof-form').hidden = true;
  $('#pin-box').hidden = true;
  const grid = $('#prof-grid');
  grid.innerHTML = '';
  for (const p of list) {
    const b = document.createElement('button');
    b.className = 'prof';
    b.innerHTML = '<div class="av"></div><div class="nm"></div>';
    b.querySelector('.av').style.background = p.color;
    b.querySelector('.av').textContent = p.name[0].toUpperCase();
    if (p.has_pin) b.querySelector('.av').insertAdjacentHTML('beforeend', '<span class="lock">🔒</span>');
    b.querySelector('.nm').textContent = p.name;
    b.addEventListener('click', () => pickProfile(p));
    grid.appendChild(b);
  }
  const add = document.createElement('button');
  add.className = 'prof add';
  add.innerHTML = '<div class="av">+</div><div class="nm">new</div>';
  add.addEventListener('click', () => showCreate(true));
  grid.appendChild(add);
  $('#prof-manage').hidden = !list.length;
  if (!list.length) showCreate(false);
}

function showCreate(canCancel) {
  body.classList.add('picking');
  $('#prof-form').hidden = false;
  $('#prof-cancel').hidden = !canCancel;
  $('#prof-form-title').textContent = profiles.length ? 'new profile' : 'first, what\'s your name? 👋';
  $('#prof-name').value = '';
  $('#prof-pin').value = '';
  $('#prof-error').textContent = '';
  $('#prof-name').focus();
}

async function pickProfile(p) {
  if (body.classList.contains('manage')) {
    if (p.has_pin) { askPin(p, 'delete'); return; }
    if (!confirm(`delete ${p.name}? all their chats and memory are gone forever`)) return;
    const r = await api.delete_profile(p.id, '');
    showProfiles(r.profiles || profiles);
    return;
  }
  if (p.has_pin) { askPin(p, 'enter'); return; }
  enterWith(await api.enter_profile(p.id, ''));
}

function askPin(p, mode) {
  pinFor = { p, mode };
  body.classList.add('picking');
  $('#pin-box').hidden = false;
  $('#pin-title').textContent = mode === 'delete' ? `PIN to delete ${p.name}` : `hey ${p.name}, enter your PIN`;
  $('#pin-input').value = '';
  $('#pin-error').textContent = '';
  $('#pin-input').focus();
}

async function submitPin() {
  const { p, mode } = pinFor;
  const pin = $('#pin-input').value;
  if (mode === 'delete') {
    if (!confirm(`delete ${p.name}? all their chats and memory are gone forever`)) return;
    const r = await api.delete_profile(p.id, pin);
    if (r.error) { $('#pin-error').textContent = r.error; return; }
    showProfiles(r.profiles);
    return;
  }
  const r = await api.enter_profile(p.id, pin);
  if (r.error) { $('#pin-error').textContent = r.error; $('#pin-input').value = ''; return; }
  enterWith(r);
}

function enterWith(r) {
  if (r.error) return;
  body.classList.remove('profiles', 'picking', 'manage', 'auth');
  me = r.profile;
  $('#me-name').textContent = me.name;
  $('#me-av').textContent = me.name[0].toUpperCase();
  $('#me-av').style.background = me.color;
  showChat(r.chat);
  refreshChatList();
  flash('happy', 1300, pick([`yooo ${me.name}!! 😤`, `ayy ${me.name}'s back 🔥`, `what's good ${me.name} 👋`]));
  input.focus();
}

async function switchProfile() {
  if (voiceOn) endVoice();
  if (busy) stopReply();
  closeAll();
  const acct = await api.account_profiles();
  if (acct) showProfiles(acct.profiles);
  else showAuth('login');
}

$('#prof-create').addEventListener('click', async () => {
  const r = await api.create_profile($('#prof-name').value, $('#prof-pin').value);
  if (r.error) { $('#prof-error').textContent = r.error; return; }
  enterWith(r);
});
$('#prof-name').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#prof-create').click(); });
$('#prof-pin').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#prof-create').click(); });
$('#prof-cancel').addEventListener('click', () => showProfiles(profiles));
$('#pin-go').addEventListener('click', submitPin);
$('#pin-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') submitPin(); });
$('#pin-back').addEventListener('click', () => showProfiles(profiles));
$('#prof-manage').addEventListener('click', () => {
  body.classList.toggle('manage');
  $('#prof-manage').textContent = body.classList.contains('manage') ? 'done' : 'manage profiles';
});

// ---------- screen sharing ----------

let sharing = null;

async function openShare() {
  if (sharing) { stopShare(); return; }
  const r = await api.share_sources();
  const list = $('#share-list');
  list.innerHTML = '';
  $('#share-note').textContent = r.error || '';
  for (const s of r.sources || []) {
    const b = document.createElement('button');
    b.className = 'src';
    b.innerHTML = `<span>${s.kind === 'screen' ? '🖥' : '🪟'}</span><span class="t"></span><span class="k">${s.kind === 'screen' ? 'screen' : 'window'}</span>`;
    b.querySelector('.t').textContent = s.title;
    b.addEventListener('click', () => startShare(s));
    list.appendChild(b);
  }
  if (voiceOn) { body.classList.add('panel-open'); $('#panel').dataset.show = 'share'; $('#panel-title').textContent = '👀 Share your screen'; }
  else openPanel('share');
}

async function startShare(s) {
  const r = await api.share_start(s.id, s.title);
  if (r.error) { $('#share-note').textContent = r.error; return; }
  sharing = s;
  $('#share-thumb').src = r.preview;
  $('#share-name').textContent = s.title;
  $('#share-badge').hidden = false;
  body.classList.add('sharing');
  body.classList.remove('panel-open');
  flash('excited', 1500, 'ooh let me see 👀');
}

function stopShare() {
  sharing = null;
  api.share_stop();
  $('#share-badge').hidden = true;
  body.classList.remove('sharing');
}
window.onShareEnded = () => { stopShare(); addNote('👀 the window you shared closed, so I stopped looking'); };

$('#share-btn').addEventListener('click', openShare);
$('#share-voice').addEventListener('click', openShare);
$('#share-stop').addEventListener('click', stopShare);

// ---------- updates ----------

let update = null;

let lastCheck = 0;

async function checkUpdate() {
  lastCheck = Date.now();
  try { update = await api.check_update(); } catch (e) { return null; }
  $('#update-btn').hidden = !update.available;
  if (update.available) $('#update-btn').title = `Flip ${update.version} is out (you have ${update.current})`;
  return update;
}

// check again when they come back to the window (at most every 10 minutes)
window.addEventListener('focus', () => { if (Date.now() - lastCheck > 10 * 60 * 1000) checkUpdate(); });

$('#check-update').addEventListener('click', async () => {
  $('#update-status').textContent = 'checking…';
  const u = await checkUpdate();
  if (!u) { $('#update-status').textContent = 'couldn\'t check right now 😵'; return; }
  $('#update-status').textContent = u.available ? `Flip ${u.version} is out! hit ⬆ Update at the top` : `you're on the newest version (${u.current}) ✓`;
});

$('#update-btn').addEventListener('click', () => {
  $('#update-text').textContent = `Flip ${update.version} is out! You have ${update.current}.`;
  $('#update-notes').textContent = update.notes || '';
  $('#update-notes').hidden = !update.notes;
  $('#update-bar-wrap').hidden = true;
  $('#update-note').textContent = 'your chats, memory and brain stay, only the app gets swapped';
  $('#update-go').disabled = false;
  openPanel('update');
});
$('#update-later').addEventListener('click', closeAll);
$('#update-go').addEventListener('click', async () => {
  if (busy) stopReply();
  if (voiceOn) endVoice();
  $('#update-go').disabled = true;
  if (!(await api.install_update())) { $('#update-note').textContent = 'couldn\'t start the update 😵 try again later'; return; }
  $('#update-bar-wrap').hidden = false;
  const poll = async () => {
    const s = await api.update_status();
    if (s.progress != null) $('#update-bar').style.width = `${Math.round(s.progress * 100)}%`;
    if (s.state === 'error') { $('#update-note').textContent = `update failed 😵 ${s.error || ''}`; $('#update-go').disabled = false; return; }
    $('#update-note').textContent = s.state === 'restarting' ? 'restarting… see you in a sec 👋' : 'downloading the new me…';
    setTimeout(poll, 400);
  };
  poll();
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
  $('.sb-brand').textContent = petName;
  pet.svg.setAttribute('aria-label', petName);
  input.placeholder = `talk to ${petName}…`;
  onPetChanged(info.pet);
  if (info.account) openAccount(info.account);
  else showAuth(info.has_accounts ? 'login' : 'signup');
  watchBrain();
  pollRoblox();
  setTimeout(checkUpdate, 4000);
  setInterval(checkUpdate, 30 * 60 * 1000);
});

setChatting(false);
autosize();
