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
const VOICE_STATUS = { listening: 'listening…', thinking: 'thinking…', working: 'working on it 🔧', talking: 'talking · talk over me to cut me off' };
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
  if (voiceOn && (busy || pet.state === 'talking')) { stopReply(); return; }  // cut him off
  if (!calm() || pet.state === 'talking') return;
  pet.poke();
  if (pet.state === 'sleeping') flash('happy', 1300, 'huh?? I\'m up I\'m up 😳');
  else setState('excited', pick(POKES));
});

// ---------- message rendering ----------

function esc(s) {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// Math like $x^2$ or $$\frac{a}{b}$$ (also \( \) and \[ \]) becomes real formulas.
const MATH = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$(?![\s$])([^$\n]+?)(?<!\s)\$(?!\d)/g;

function renderMath(tex, display) {
  if (!window.katex) return null;
  try { return katex.renderToString(tex, { displayMode: display, throwOnError: false, output: 'html' }); } catch (e) { return null; }
}

function inline(t) {
  const math = [];
  t = t.replace(MATH, (all, d1, d2, i1, i2) => {
    const html = renderMath(d1 || d2 || i1 || i2, !!(d1 || d2));
    if (html == null) return all;
    math.push(html);
    return (d1 || d2) ? `\u0001${math.length - 1}\u0001` : `\u0000${math.length - 1}\u0000`;
  });
  t = t.replace(/\n*\u0001(\d+)\u0001\n*/g, '\u0000$1\u0000');  // formulas on their own line bring their own spacing
  return esc(t)
    .replace(/`([^`\n]+)`/g, '<code class="inline">$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
    .replace(/\n/g, '<br>')
    .replace(/\u0000(\d+)\u0000/g, (_, i) => math[+i]);
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
  if (stream.talk && (voiceOn || !muted)) speaker.feed(piece);
  if (voiceOn) $('#cap-pet').textContent = captionText(stream.text);
  if (!['working', 'talking'].includes(pet.state)) setState('thinking', 'typing…');
  else if (pet.state === 'working') setState('thinking', 'typing…');
  if (stick) toBottom();
};

const captionText = (t) => t.replace(/```[\s\S]*?(```|$)/g, ' ').replace(/[*_`#]/g, '');

// Called from Python when he throws away a reply that repeated an earlier one and tries again.
window.onResetText = () => {
  if (!stream) return;
  stream.text = '';
  stream.b.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
  if (stream.talk) stopSpeaking();
};

// Called from Python when he uses a tool (memory, Roblox Studio…).
window.onTool = (name) => {
  if (name === 'remember') { addNote('🧠 saved to memory'); return; }
  if (name === 'forget') { addNote('🧠 forgot something'); return; }
  if (name === 'math') { setState('working', 'calculating…'); return; }
  setState('working', 'working in Roblox Studio…');
};

// Called from Python when he's decided what kind of message this is.
const ROUTE_SAID = { math: 'calculating…', live: 'reading the round…', valorant: 'thinking like a coach…',
  code: 'looking at the code…', roblox: 'looking at the code…' };
window.onRoute = (kind, think) => {
  if (!stream) return;
  const said = think ? 'thinking it through…' : ROUTE_SAID[kind];
  if (said && pet.state !== 'talking') setState('thinking', said);
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
  const talk = voiceOn || !muted;
  stream = { b, text: '', talk };
  voiceStats = { start: Date.now() };

  let res;
  try { res = await api.send(chatId, text, voiceOn); } catch (e) { res = { error: `something broke 😭 (${e})` }; }
  const written = stream.text;
  stream = null;
  voiceStats.replyDone = Date.now();

  if (res.error) {
    stopSpeaking();
    setBusy(false);
    row.classList.add('error');
    b.innerHTML = format(res.error);
    if (voiceOn) $('#cap-pet').textContent = res.error;
    setState(voiceOn ? 'listening' : 'idle', 'uh oh 😵');
    return;
  }

  b.innerHTML = format(res.reply);
  if (res.stopped) row.insertAdjacentHTML('beforeend', '<div class="stopped">stopped</div>');
  else if (res.secs != null) row.insertAdjacentHTML('beforeend', `<div class="meta">${res.secs}s${mode !== 'auto' ? ` · ${MODE_LABEL[mode]}` : ''}</div>`);
  if (chatTitle === 'New chat' || !allChats.some((c) => c.id === chatId)) {
    setTitle(res.title);
    refreshChatList();
  }
  if (voiceOn) $('#cap-pet').textContent = captionText(res.reply);
  if (talk && (voiceOn || !muted) && !res.stopped) {
    if (!written.trim()) speaker.feed(res.reply);  // nothing came in live (like a canned reply)
    speaker.finish();  // say whatever's left
    await speaker.idle();
  }
  setBusy(false);
  if (voiceOn) setState('listening');
  else if (!res.stopped && /let'?s go|🔥|goated|\bW\b|hype|🐐|💪|🎉/i.test(res.reply)) flash('happy', 1300);
  else setState('idle');
}

function stopReply() {
  if (!api) return;
  api.stop();
  stopSpeaking();
}

// ---------- voice out: he talks while he types ----------

// Where to cut what he's written into pieces to say: at the end of a sentence (the first piece can
// be tiny so he starts talking right away), or at a comma if a sentence runs long.
function findCut(s, first) {
  const re = /[.!?…]+["'”’)\]]*\s+|\n+/g;
  let m;
  while ((m = re.exec(s))) {
    const end = m.index + m[0].length;
    if (s.slice(0, end).trim().length >= (first ? 1 : 40)) return end;
  }
  const soft = first ? 12 : 110;
  const comma = /[,;:–—]\s+|\s-\s/g;
  while ((m = comma.exec(s))) {
    const end = m.index + m[0].length;
    if (end >= soft) return end;
  }
  if (first) {  // no punctuation yet: say the first few words right away instead of waiting
    const words = /\S+\s+/g;
    let n = 0;
    while ((m = words.exec(s))) if (++n >= 5 && m.index + m[0].length >= 24) return m.index + m[0].length;
  }
  return 0;
}

const speakableBit = (t) => /[\p{L}\p{N}]/u.test(t.replace(/\p{Extended_Pictographic}/gu, ''));

class Speaker {
  constructor() { this.reset(); }

  reset() {
    this.token = {};             // changes when he gets cut off, so leftover work is dropped
    this.text = '';              // everything he's written so far
    this.pos = 0;                // how much of it is handled already
    this.inCode = false;
    this.saidCode = false;
    this.first = true;
    this.making = Promise.resolve();   // his voice gets made one piece at a time…
    this.playing = Promise.resolve();  // …and played in order while the next piece is made
    this.queued = 0;
  }

  get active() { return this.queued > 0; }

  feed(piece) { this.text += piece; this._pump(false); }

  finish() { this._pump(true); }

  // Speak a whole text (voice test, and replies that weren't written live).
  async say(text) { this.reset(); this.feed(text); this.finish(); await this.idle(); }

  async idle() { while (this.active) await this.playing; }

  _pump(final) {
    for (;;) {
      const rest = this.text.slice(this.pos);
      if (this.inCode) {  // skip code, it's in the chat
        const end = rest.indexOf('```');
        if (end < 0) { if (final) this.pos = this.text.length; return; }
        this.pos += end + 3;
        this.inCode = false;
        continue;
      }
      const fence = rest.indexOf('```');
      if (fence >= 0) {
        this._say(rest.slice(0, fence));
        if (!this.saidCode) this._say('I dropped the code in the chat.');
        this.saidCode = true;
        this.inCode = true;
        this.pos += fence + 3;
        continue;
      }
      if (final) { this._say(rest.replace(/`+$/, '')); this.pos = this.text.length; return; }
      const cut = findCut(rest.replace(/`{1,2}$/, ''), this.first);  // a backtick at the end might start code
      if (!cut) return;
      this._say(rest.slice(0, cut));
      this.pos += cut;
    }
  }

  _say(text) {
    text = text.trim();
    if (!speakableBit(text)) return;
    this.first = false;
    const token = this.token;
    this.queued++;
    if (!voiceStats.firstSay) voiceStats.firstSay = Date.now();
    const clip = this.making = this.making
      .then(() => (this.token === token ? api.say(text) : null))
      .catch(() => null);
    this.playing = this.playing.then(async () => {
      const c = await clip;
      if (this.token !== token) return;
      if (!voiceStats.firstPlay) voiceStats.firstPlay = Date.now();
      if (c) await playClip(c);
      else await speakWithWindows(text);
    }).catch(() => {}).finally(() => { if (this.token === token) this.queued--; });
  }
}

const speaker = new Speaker();
let voiceStats = {};  // timings, checked by the build's app test

function stopSpeaking() {
  speaker.reset();
  if (currentAudio) currentAudio.pause();
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (speakDone) speakDone();
}
window.stopSpeaking = stopSpeaking;

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

// The mic goes through this window because its mic has echo cancellation: he doesn't hear himself
// through your speakers, so you can talk over him. Audio goes to Python 100 ms at a time (16 kHz).
const GRAB = `class Grab extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
}
registerProcessor('flip-grab', Grab);`;

class Mic {
  constructor(onchunk) {
    this.onchunk = onchunk;   // gets Int16Array pieces of 16 kHz audio
    this.buf = [];
    this.size = 0;
    this.ready = false;
  }

  async open() {
    const want = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: want });
    const pickedId = await pickedMic();
    const nowId = this.stream.getAudioTracks()[0]?.getSettings().deviceId;
    if (pickedId && pickedId !== nowId) {  // they picked a mic in Settings
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio: { ...want, deviceId: { exact: pickedId } } });
        this.stream.getTracks().forEach((t) => t.stop());
        this.stream = s;
      } catch (e) {}
    }
    this.ctx = new AudioContext();  // (Chromium can't feed a mic into a 16 kHz one, so it's converted below)
    const url = URL.createObjectURL(new Blob([GRAB], { type: 'application/javascript' }));
    await this.ctx.audioWorklet.addModule(url);
    this.src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, 'flip-grab');
    this.node.port.onmessage = (e) => this._take(e.data);
    const mute = this.ctx.createGain();
    mute.gain.value = 0;  // keeps the audio flowing without playing your mic back to you
    this.src.connect(this.node);
    this.node.connect(mute);
    mute.connect(this.ctx.destination);
    await this.ctx.resume();
    this.ready = true;
  }

  _take(samples) {
    this.buf.push(samples);
    this.size += samples.length;
    const block = Math.round(this.ctx.sampleRate / 10);  // 100 ms
    if (this.size < block) return;
    const all = new Float32Array(this.size);
    let at = 0;
    for (const b of this.buf) { all.set(b, at); at += b.length; }
    const used = Math.floor(all.length / block) * block;
    this.buf = [all.slice(used)];
    this.size = all.length - used;
    const x = to16k(all.subarray(0, used), this.ctx.sampleRate);
    const pcm = new Int16Array(x.length);
    let sum = 0;
    for (let i = 0; i < x.length; i++) {
      const v = Math.max(-1, Math.min(1, x[i]));
      pcm[i] = v * 32767;
      sum += v * v;
    }
    this.level = Math.min(1, Math.sqrt(sum / x.length) * 12);
    this.onchunk(pcm);
  }

  close() {
    this.ready = false;
    try { this.stream?.getTracks().forEach((t) => t.stop()); } catch (e) {}
    try { this.ctx?.close(); } catch (e) {}
  }
}

// 16 kHz audio for the speech detector: averages the samples that fall into each new one
// (which also filters out the highs that would otherwise turn into noise).
function to16k(x, rate) {
  if (rate === 16000) return x;
  const r = rate / 16000, n = Math.round(x.length / r), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    if (r < 1) { out[i] = x[Math.min(x.length - 1, Math.floor(i * r))]; continue; }
    const a = Math.floor(i * r), b = Math.min(x.length, Math.max(a + 1, Math.floor((i + 1) * r)));
    let sum = 0;
    for (let j = a; j < b; j++) sum += x[j];
    out[i] = sum / (b - a);
  }
  return out;
}

function toBase64(int16) {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

// The mic picked in Settings (by name), as this window knows it.
async function pickedMic() {
  let name = '';
  try { name = (await api.mic_name() || '').toLowerCase(); } catch (e) {}
  if (!name) return null;
  const mics = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput' && d.label);
  const m = mics.find((d) => d.label.toLowerCase().startsWith(name) || name.startsWith(d.label.toLowerCase()));
  return m ? m.deviceId : null;
}

let callMic = null;
let micError = '';
let feeding = false;
let unsent = [];
let injected = [];  // speech the build's app test plays into the call
let heardQueue = Promise.resolve();

async function feedCall(pcm) {
  if (injected.length) pcm = injected.shift();
  unsent.push(pcm);
  if (callMic && voiceOn && ['listening', 'excited'].includes(pet.state)) pet.level(callMic.level || 0);
  if (feeding) return;
  feeding = true;
  while (unsent.length && voiceOn) {
    const n = unsent.reduce((a, p) => a + p.length, 0);
    const all = new Int16Array(n);
    let at = 0;
    for (const p of unsent) { all.set(p, at); at += p.length; }
    unsent = [];
    let r = null;
    // while he's writing or talking it takes clearer speech to count, so echo and coughs don't cut him off
    try { r = await api.voice_feed(toBase64(all), busy || speaker.active); } catch (e) {}
    if (r && r.talking) youreTalking();
  }
  feeding = false;
}

// They started talking: if he's talking or still writing, he stops and listens.
function youreTalking() {
  if (busy || speaker.active) {
    voiceStats.bargeIn = Date.now();
    stopReply();
  }
  if (pet.state !== 'listening') setState('listening');
}

// Called from Python while they're still talking: what it's understood so far.
window.onHearing = (text) => {
  if (!voiceOn) return;
  $('#cap-you').textContent = `“${text}…”`;
  if (!busy) $('#cap-pet').textContent = '';
};

// Called from Python with what they said in the call.
window.onHeard = (text) => {
  heardQueue = heardQueue.then(async () => {
    if (!voiceOn) return;
    const until = Date.now() + 8000;
    if (busy) stopReply();
    while (busy && Date.now() < until) await new Promise((r) => setTimeout(r, 50));
    if (voiceOn) await sendHeard(text);
  });
};

function sendHeard(text) {
  send(text);  // don't wait for his reply, so the next thing they say can cut in
  return new Promise((r) => setTimeout(r, 50));
}

// Used by the build's app test: 16 kHz speech (base64) that goes into the call as if it came from the mic.
window.injectSpeech = (b64) => {
  const bin = atob(b64);
  const all = new Int16Array(bin.length / 2);
  for (let i = 0; i < all.length; i++) all[i] = (bin.charCodeAt(i * 2) | (bin.charCodeAt(i * 2 + 1) << 8)) << 16 >> 16;
  for (let i = 0; i < all.length; i += 1600) injected.push(all.slice(i, i + 1600));
};

async function startVoice() {
  if (!api || voiceOn || !me) return;
  if (busy) stopReply();
  closeAll();
  voiceOn = true;
  micError = '';
  api.voice_state(true);
  body.classList.add('voice');
  $('#cap-you').textContent = '';
  $('#cap-pet').textContent = pick(['yo, I\'m listening 👂', 'talk to me bro', 'what\'s good? I\'m all ears']);
  pet.wake();
  setState('listening');
  const r = await api.voice_call_start();
  if (r.error) { voiceFailed(r.error); return; }
  const mic = new Mic(feedCall);
  try {
    await mic.open();
  } catch (e) {
    mic.close();
    micError = `${e.name || 'Error'}: ${e.message || e}`;
    console.warn('Window mic failed, using Flip\'s own mic', micError);
    api.voice_call_stop();
    if (voiceOn) listenWithFlipsMic();
    return;
  }
  if (!voiceOn) { mic.close(); return; }
  callMic = mic;
}

// Backup: Flip listens with his own mic code (then you can't talk over him).
async function listenWithFlipsMic() {
  while (voiceOn) {
    if (busy) { await new Promise((r) => setTimeout(r, 200)); continue; }
    setState('listening');
    pollLevel(true);
    const r = await api.voice_listen();
    pollLevel(false);
    if (!voiceOn || r.ended) break;
    if (r.error) { voiceFailed(r.error); return; }
    if (r.text) await send(r.text);
  }
}

function voiceFailed(error) {
  $('#cap-pet').textContent = error;
  setChatting(true);
  addMsg('pet', error, 'error');
  endVoice();
}

function endVoice() {
  if (!voiceOn) return;
  voiceOn = false;
  api.voice_state(false);
  pollLevel(false);
  if (callMic) { callMic.close(); callMic = null; }
  unsent = [];
  injected = [];
  api.voice_call_stop();
  api.voice_cancel();
  if (busy) api.stop();
  stopSpeaking();
  pet.level(0);
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
  $('#set-brain').value = s.brain_size || 'smart';
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
  const r = await api.save_settings(currentSettings());
  $('#set-note').textContent = 'saved ✓ voice changes work right away, the rest after you reopen me 🔁';
  if (r && r.brain_switching) {
    closeAll();
    watchBrain();  // shows the download/switch progress; the old brain gets deleted after
  }
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
    brain_size: $('#set-brain').value,
  };
}
$('#voice-test').addEventListener('click', async () => {
  await api.save_settings(currentSettings());  // voice settings apply right away
  stopSpeaking();
  speaker.say(pick(['yo, it\'s me. how do I sound?', 'this is my voice, lowkey fire right?', 'testing, testing. I\'m ready to clutch.']));
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

const MODE_LABEL = { auto: '✨ Auto', fast: '⚡ Fast', think: '🧠 Think', math: '🧮 Math', valorant: '🎯 Valorant', code: '💻 Code' };
const MODE_SAID = { auto: 'auto mode: I pick what fits ✨', fast: 'quick replies on ⚡', think: 'think mode: I\'ll work it out properly 🧠',
  math: 'math mode 🧮 exact answers only', valorant: 'coach mode 🎯 give me the round', code: 'code mode 💻 paste it in' };
let mode = 'auto';

function showMode(m, s = {}) {
  mode = MODE_LABEL[m] ? m : 'auto';
  fast = mode === 'fast';
  $('#mode-btn').textContent = MODE_LABEL[mode];
  $('#mode-btn').classList.toggle('on', mode !== 'auto');
  const info = s.model ? `\nbrain: ${s.model}${s.hardware ? ` on ${s.hardware}` : ''}` : '';
  $('#mode-btn').title = `How Flip answers: ${MODE_LABEL[mode]}${info}`;
  for (const b of document.querySelectorAll('#mode-menu button')) b.classList.toggle('current', b.dataset.mode === mode);
}
function showFast(on, s = {}) { showMode(s.mode || (on ? 'fast' : 'auto'), s); }

$('#mode-btn').addEventListener('click', (e) => { e.stopPropagation(); $('#mode-menu').hidden = !$('#mode-menu').hidden; });
document.addEventListener('click', (e) => { if (!e.target.closest('.mode-wrap')) $('#mode-menu').hidden = true; });
async function setMode(m) {
  $('#mode-menu').hidden = true;
  if (voiceOn && m !== mode) {}  // fine mid-call: applies from the next thing you say
  const s = await api.set_mode(m);
  showMode(s.mode, s);
  if (calm()) setState('idle', MODE_SAID[mode]);
}
for (const b of document.querySelectorAll('#mode-menu button')) b.addEventListener('click', () => setMode(b.dataset.mode));

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
  if ('mode' in s || 'fast' in s) showFast(s.fast, s);
  showVision(!!s.vision);
  if (s.state === 'ready') {
    if (body.classList.contains('setup')) {
      body.classList.remove('setup', 'setup-error');
      const cpu = /^CPU/.test(s.hardware || '');
      flash('happy', 2500, cpu ? 'brain loaded, but only on your processor 🐢 replies will be slower'
        : 'brain loaded, let\'s cook 🧠🔥');
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
