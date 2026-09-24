// Flip's body: the SVG drawing plus the controls both windows use to animate him.

const PET_SVG = `
<svg class="pet" viewBox="0 0 200 200" role="img" aria-label="Flip">
  <defs>
    <radialGradient id="g-body" cx="38%" cy="30%" r="80%">
      <stop offset="0" stop-color="#c2ffe8"/>
      <stop offset=".5" stop-color="#5ff0b8"/>
      <stop offset="1" stop-color="#26b889"/>
    </radialGradient>
    <linearGradient id="g-cap" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ff82a6"/>
      <stop offset="1" stop-color="#ff3f73"/>
    </linearGradient>
  </defs>

  <g id="waves">
    <path class="w1" d="M20 96 Q10 112 20 128"/>
    <path class="w2" d="M8 88 Q-6 112 8 136"/>
    <path class="w1" d="M180 96 Q190 112 180 128"/>
    <path class="w2" d="M192 88 Q206 112 192 136"/>
  </g>

  <g id="squish">
    <g id="bob">
      <ellipse class="foot" cx="76" cy="178" rx="17" ry="9"/>
      <ellipse class="foot" cx="124" cy="178" rx="17" ry="9"/>
      <ellipse id="arm-l" class="arm" cx="30" cy="130" rx="10" ry="16"/>
      <ellipse id="arm-r" class="arm" cx="170" cy="130" rx="10" ry="16"/>
      <path class="body" d="M100 44 C152 44 172 80 172 120 C172 162 142 180 100 180 C58 180 28 162 28 120 C28 80 48 44 100 44 Z"/>
      <ellipse class="belly" cx="100" cy="152" rx="42" ry="22"/>
      <ellipse class="cheek" cx="60" cy="130" rx="11" ry="7"/>
      <ellipse class="cheek" cx="140" cy="130" rx="11" ry="7"/>

      <g id="look">
        <g id="eyes">
          <g id="eyes-open">
            <ellipse class="eye" cx="76" cy="110" rx="11" ry="14"/>
            <ellipse class="eye" cx="124" cy="110" rx="11" ry="14"/>
            <circle class="shine" cx="72" cy="104" r="4.2"/>
            <circle class="shine" cx="80" cy="116" r="2"/>
            <circle class="shine" cx="120" cy="104" r="4.2"/>
            <circle class="shine" cx="128" cy="116" r="2"/>
          </g>
          <g id="eyes-closed" class="line">
            <path d="M65 112 Q76 120 87 112"/>
            <path d="M113 112 Q124 120 135 112"/>
          </g>
          <g id="eyes-happy" class="line">
            <path d="M65 115 Q76 101 87 115"/>
            <path d="M113 115 Q124 101 135 115"/>
          </g>
        </g>
      </g>

      <path id="mouth-smile" class="line" d="M90 132 Q100 142 110 132"/>
      <g id="mouth-open">
        <ellipse class="mouth" cx="100" cy="138" rx="12" ry="10"/>
        <ellipse class="tongue" cx="100" cy="143" rx="7" ry="4"/>
      </g>

      <g id="cap" transform="rotate(-8 100 60)">
        <path class="brim" d="M138 72 C160 66 186 70 192 80 C178 86 156 84 136 80 Z"/>
        <path class="cap" d="M50 80 C50 26 150 26 150 80 C120 71 80 71 50 80 Z"/>
        <circle class="cap-btn" cx="100" cy="39" r="5"/>
        <path class="bolt" d="M104 50 L93 64 L101 64 L96 76 L109 60 L101 60 Z"/>
      </g>
    </g>
  </g>

  <g id="thought">
    <circle cx="150" cy="52" r="3.5"/>
    <circle cx="160" cy="40" r="5.5"/>
    <ellipse cx="180" cy="18" rx="24" ry="15"/>
    <circle class="d d1" cx="170" cy="18" r="3.2"/>
    <circle class="d d2" cx="180" cy="18" r="3.2"/>
    <circle class="d d3" cx="190" cy="18" r="3.2"/>
  </g>

  <g id="zzz">
    <text class="z z1" x="142" y="58">z</text>
    <text class="z z2" x="154" y="42">z</text>
    <text class="z z3" x="168" y="24">Z</text>
  </g>

  <g id="sparkles">
    <path transform="translate(28 58)" d="M0 -9 L2.5 -2.5 L9 0 L2.5 2.5 L0 9 L-2.5 2.5 L-9 0 L-2.5 -2.5 Z"/>
    <path transform="translate(176 44)" d="M0 -7 L2 -2 L7 0 L2 2 L0 7 L-2 2 L-7 0 L-2 -2 Z"/>
    <path transform="translate(14 150)" d="M0 -6 L1.8 -1.8 L6 0 L1.8 1.8 L0 6 L-1.8 1.8 L-6 0 L-1.8 -1.8 Z"/>
    <path transform="translate(188 150)" d="M0 -8 L2.2 -2.2 L8 0 L2.2 2.2 L0 8 L-2.2 2.2 L-8 0 L-2.2 -2.2 Z"/>
  </g>
</svg>`;

class Pet {
  // stage: element whose data-state drives the animations; host: where the SVG goes.
  constructor(stage, host) {
    host.innerHTML = PET_SVG;
    this.stage = stage;
    this.svg = host.querySelector('svg');
    this.squish = this.svg.querySelector('#squish');
    this.state = 'idle';
    this.onchange = null;
    this._sleepTimer = 0;
    this._flashTimer = 0;
    this._fakeTalk = 0;
    this.squish.addEventListener('animationend', () => this.squish.classList.remove('poke'));
    this.set('idle');
  }

  set(state) {
    clearTimeout(this._flashTimer);
    clearTimeout(this._sleepTimer);
    this.state = state;
    this.stage.dataset.state = state;
    if (state === 'idle') this._sleepTimer = setTimeout(() => this.set('sleeping'), 120000);
    if (this.onchange) this.onchange(state);
  }

  // Show a state for a moment, then go back to idle (unless something else happened meanwhile).
  flash(state, ms) {
    this.set(state);
    this._flashTimer = setTimeout(() => { if (this.state === state) this.set('idle'); }, ms);
  }

  wake() {
    if (this.state === 'sleeping') this.set('idle');
  }

  mouth(level) {
    this.svg.style.setProperty('--mouth', (0.25 + level * 1.1).toFixed(2));
  }

  // Wiggle the mouth without real audio (used by the desktop pet while he talks).
  fakeTalk(on) {
    clearInterval(this._fakeTalk);
    if (on) this._fakeTalk = setInterval(() => this.mouth(0.2 + Math.random() * 0.8), 90);
    else this.mouth(0);
  }

  level(v) {
    this.svg.style.setProperty('--lvl', Math.min(1, v).toFixed(2));
  }

  // Eyes follow a point on the page (the mouse).
  lookAt(x, y) {
    const r = this.svg.getBoundingClientRect();
    const dx = x - (r.left + r.width / 2);
    const dy = y - (r.top + r.height * 0.55);
    const d = Math.max(1, Math.hypot(dx, dy));
    const k = Math.min(1, d / 180);
    this.svg.style.setProperty('--lx', `${((dx / d) * 7 * k).toFixed(1)}px`);
    this.svg.style.setProperty('--ly', `${((dy / d) * 5 * k).toFixed(1)}px`);
  }

  lookAway() {
    this.svg.style.setProperty('--lx', '0px');
    this.svg.style.setProperty('--ly', '0px');
  }

  poke() {
    this.squish.classList.remove('poke');
    void this.squish.getBBox();
    this.squish.classList.add('poke');
  }
}
