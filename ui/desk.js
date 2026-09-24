// The little guy who lives on your desktop.
const stage = document.getElementById('stage');
const bubble = document.getElementById('bubble');
const pet = new Pet(stage, document.getElementById('pet-host'));
const voiceBtn = document.getElementById('voice-btn');
const pinBtn = document.getElementById('pin-btn');

const HELLOS = ['heyyy 👋', 'sup bro 😎', 'you rang? 👀', 'what we cooking?', 'hi hi hi', 'W cursor ngl'];
const POKES = ['ayo 😭', 'that tickles fr', 'hehe', 'drag me around, I don\'t mind', 'poke me again, I dare you', 'boop', 'hey!! 😤'];
const pick = (a) => a[Math.floor(Math.random() * a.length)];

let api = null;
let hovering = false;
let mirrored = 'idle';
let voiceOn = false;
let pinned = true;
let bubbleTimer = 0;
let downAt = null;

function say(text, ms = 6000) {
  bubble.textContent = text;
  bubble.classList.add('show');
  clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => bubble.classList.remove('show'), ms);
}

// The chat window tells us what he's doing (thinking, talking…) so both stay in sync.
function mirror(state) {
  mirrored = state;
  pet.fakeTalk(state === 'talking');
  if (!hovering || state !== 'idle') pet.set(state === 'excited' ? 'idle' : state);
}

function voiceChanged(on) {
  voiceOn = on;
  voiceBtn.classList.toggle('on', on);
  voiceBtn.title = on ? 'End voice chat' : 'Talk to me (voice chat)';
  document.body.classList.toggle('voice', on);
  if (on) say('I\'m listening 👂 just talk', 2500);
}

function showPinned(on) {
  pinned = on;
  pinBtn.classList.toggle('on', on);
  pinBtn.title = on ? 'Pinned on top of other windows (click to unpin)' : 'Pin on top of other windows';
}

// When the mouse is on him: he gets hyped, waves, and his eyes follow the cursor.
document.addEventListener('mousemove', (e) => pet.lookAt(e.clientX, e.clientY));
document.body.addEventListener('mouseenter', () => {
  hovering = true;
  document.body.classList.add('hover');
  if (['idle', 'sleeping'].includes(mirrored)) {
    pet.set('excited');
    if (Math.random() < 0.5) say(pick(HELLOS), 2500);
  }
});
document.body.addEventListener('mouseleave', () => {
  hovering = false;
  document.body.classList.remove('hover');
  pet.lookAway();
  pet.set(mirrored === 'excited' ? 'idle' : mirrored);
});

// Drag him anywhere. Tapping him just makes him react (the chat only opens from the 💬 button).
pet.svg.addEventListener('mousedown', (e) => { downAt = [e.screenX, e.screenY]; });
pet.svg.addEventListener('click', (e) => {
  const moved = downAt && Math.hypot(e.screenX - downAt[0], e.screenY - downAt[1]) > 5;
  downAt = null;
  if (moved) return;
  if (voiceOn && mirrored === 'talking') { api && api.pet_interrupt(); return; }  // cut him off
  pet.poke();
  say(pick(POKES), 2200);
});

document.getElementById('chat-btn').addEventListener('click', () => api && api.open_chat());
document.getElementById('hide-btn').addEventListener('click', () => api && api.hide_pet());
voiceBtn.addEventListener('click', () => api && api.pet_voice());
pinBtn.addEventListener('click', async () => { if (api) showPinned(await api.pet_pin(!pinned)); });

window.addEventListener('pywebviewready', async () => {
  api = window.pywebview.api;
  const info = await api.pet_info();
  showPinned(info.pinned);
  if (info.voice) voiceChanged(true);
  pet.flash('happy', 1300);
  say(pick(['I\'m out here now 😎', 'desktop mode activated 🔥', 'yo I live here now']), 3000);
});
