// The little guy who lives on your desktop.
const stage = document.getElementById('stage');
const bubble = document.getElementById('bubble');
const pet = new Pet(stage, document.getElementById('pet-host'));

const HELLOS = ['heyyy 👋', 'sup bro 😎', 'you rang? 👀', 'what we cooking?', 'hi hi hi', 'W cursor ngl'];
const POKES = ['ayo 😭', 'that tickles fr', 'hehe', 'drag me around, I don\'t mind', 'poke me again, I dare you'];
const pick = (a) => a[Math.floor(Math.random() * a.length)];

let api = null;
let hovering = false;
let mirrored = 'idle';
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

// Drag him anywhere; a click without dragging opens the chat.
pet.svg.addEventListener('mousedown', (e) => { downAt = [e.screenX, e.screenY]; });
pet.svg.addEventListener('click', (e) => {
  const moved = downAt && Math.hypot(e.screenX - downAt[0], e.screenY - downAt[1]) > 5;
  downAt = null;
  if (moved || !api) return;
  pet.poke();
  if (e.detail === 1) api.open_chat();
});
pet.svg.addEventListener('contextmenu', (e) => { e.preventDefault(); pet.poke(); say(pick(POKES), 2500); });

document.getElementById('chat-btn').addEventListener('click', () => api && api.open_chat());
document.getElementById('hide-btn').addEventListener('click', () => api && api.hide_pet());

window.addEventListener('pywebviewready', () => {
  api = window.pywebview.api;
  pet.flash('happy', 1300);
  say(pick(['I\'m out here now 😎', 'desktop mode activated 🔥', 'yo I live here now']), 3000);
});
