// SVG-based mascot handler for Compy UI / boopi assistant.
// Plays native 2D SVG elements directly using requestAnimationFrame.

let startTime = 0;
let lastTimestamp = 0;
let isAnimating = false;

let currentState = 'idle';
let previousState = 'idle';
let stateTime = 0;

let originalBobGroupHTML = '';
let currentMascotSVGFile = '';

const MASCOT_STATE_SVGS = {
  'drinking_boba': 'Boobateaholding.svg',
  'reading': 'Bookreading.svg',
  'writing': 'Bookreading.svg',
  'drinking_coffee': 'Cupholding.svg',
  'chilling': 'hatwithbag.svg',
  'happy': 'celebrate.svg',
  'excited': 'celebrate.svg',
  'celebrating': 'celebrate.svg',
  'praise': 'syicsmile.svg',
  'concerned': 'Crying.svg',
  'error': 'Crying.svg',
  'angry': 'Crying.svg',
  'confused': 'syicsmile.svg',
  'laughing': 'Laughing.svg',
  'wink': 'wink.svg',
  'bigsmile': 'bigsmilewithblackcap.svg',
  'idle_pose': 'idelMascot.svg'
};

// Conversation-aware acknowledgment face picker config
const ACK_FACE_HOLD_MS = 1200;    // How long to hold an ack face before returning to idle
const VISEME_DECAY_MS = 180;     // How long mouth takes to decay to silence after speech ends

let ackTimer = null;
let isHoldingAckFace = false;    // True while an ack face is being held

// Target variables for smooth LERPing
let targetThinkProgress = 0;
let currentThinkProgress = 0;

let targetSleepProgress = 0;
let currentSleepProgress = 0;

let targetTalkingProgress = 0;
let currentTalkingProgress = 0;

let targetWavingProgress = 1; 
let currentWavingProgress = 1;

let targetSteadyProgress = 0; 
let currentSteadyProgress = 0;

let targetBookProgress = 0;
let currentBookProgress = 0;

let targetCoffeeProgress = 0;
let currentCoffeeProgress = 0;

let targetBobaProgress = 0;
let currentBobaProgress = 0;

// Viseme queue variables
let visemeQueue = [];
let speechTimer = 0;
let lastVisemeSetTime = 0;
let lastVisemeCode = 'sil';

// Accumulated speech for ack-face analysis
let accumulatedSpeechForAck = "";
let thinkingRoundCount = 0;  // Track consecutive thinking rounds

// Emoji reaction sets
const HAPPY_REACTION_EMOJIS = new Set(['✅', '🎉', '🙌', '😊', '😄', '👍', '💪']);
const PROUD_REACTION_EMOJIS = new Set(['⭐', '🌟', '🏆', '🎯', '💯', '🚀', '✨', '🥇']);
const CURIOUS_REACTION_EMOJIS = new Set(['🔍', '💭', '🧐', '🤓', '👀']);
const CONFUSED_REACTION_EMOJIS = new Set(['🤔', '❓', '❔']);
const CAUTIOUS_REACTION_EMOJIS = new Set(['⚠️', '⚠', '💡', '⚡']);
const CONCERNED_REACTION_EMOJIS = new Set(['🚨', '❌', '😕', '😟']);
const CELEBRATING_REACTION_EMOJIS = new Set(['🥳', '🍾', '🎊', '🎈', '🪅']);
const DANCING_REACTION_EMOJIS = new Set(['💃', '🕺', '🎵', '🎶', '🎸']);
const WAVING_REACTION_EMOJIS = new Set(['👋', '🤝', '🫡']);

// Text analysis patterns  
const CONCERNED_TEXT_RE = /\b(sorry|apolog(?:y|ize|ise)|failed|failure|error|cannot|can't|unable|blocked|problem)\b/i;
const CONFUSED_TEXT_RE = /\b(not sure|unclear|ambiguous|clarify|which one|need more|can you confirm|maybe)\b/i;
const HAPPY_TEXT_RE = /\b(done|completed|fixed|success|successful|ready|all set|great|nice)\b/i;
const PROUD_TEXT_RE = /\b(successfully completed|all tasks? (done|finished)|mission accomplished|everything (works?|is working)|all (checks?|tests?) pass(ed)?)\b/i;
const CURIOUS_TEXT_RE = /\b(interesting|fascinating|curious(ly)?|let me (check|look|investigate)|i('ll)? (look|check) into|turns? out to be)\b/i;
const CAUTIOUS_TEXT_RE = /\b(be careful|warning|caution|heads? up|please note|make sure|important to note|note that|worth (noting|mentioning))\b/i;
const CELEBRATING_TEXT_RE = /\b(congrat(ulations|s)?|well done|bravo|hooray|woohoo|amazing|fantastic|incredible|awesome work)\b/i;
const GREETING_TEXT_RE = /^(hello|hey|hi there|good (morning|afternoon|evening)|welcome back|greetings|howdy)[!.,]?(?:\s|$)/i;

// Color theme definitions
const PALETTES = {
  yellow: {
    bodyFill: '#F7D145',
    neckShadowColor: '#B23C05',
    bodyHighlightMatrix: '0 0 0 0 0.962384 0 0 0 0 0.860378 0 0 0 0 0.484572 0 0 0 1 0',
    bodyShadowMatrix: '0 0 0 0 0.797063 0 0 0 0 0.575703 0 0 0 0 0.0980312 0 0 0 1 0',
    headHighlightMatrix: '0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 1 0',
    headShadowMatrix: '0 0 0 0 0.797063 0 0 0 0 0.575703 0 0 0 0 0.0980312 0 0 0 1 0',
    armHighlightMatrix: '0 0 0 0 0.973501 0 0 0 0 0.909066 0 0 0 0 0.671677 0 0 0 1 0',
    armShadowMatrix: '0 0 0 0 0.796078 0 0 0 0 0.576471 0 0 0 0 0.0980392 0 0 0 1 0'
  },
  burgundy: {
    bodyFill: '#8A2647',
    neckShadowColor: '#541128',
    bodyHighlightMatrix: '0 0 0 0 0.607843 0 0 0 0 0.235294 0 0 0 0 0.313726 0 0 0 1 0',
    bodyShadowMatrix: '0 0 0 0 0.27451 0 0 0 0 0.0745098 0 0 0 0 0.129412 0 0 0 1 0',
    headHighlightMatrix: '0 0 0 0 0.854902 0 0 0 0 0.611765 0 0 0 0 0.690196 0 0 0 1 0',
    headShadowMatrix: '0 0 0 0 0.27451 0 0 0 0 0.0745098 0 0 0 0 0.129412 0 0 0 1 0',
    armHighlightMatrix: '0 0 0 0 0.607843 0 0 0 0 0.235294 0 0 0 0 0.313726 0 0 0 1 0',
    armShadowMatrix: '0 0 0 0 0.27451 0 0 0 0 0.0745098 0 0 0 0 0.129412 0 0 0 1 0'
  },
  navy: {
    bodyFill: '#234B74',
    neckShadowColor: '#16324D',
    bodyHighlightMatrix: '0 0 0 0 0.270588 0 0 0 0 0.447059 0 0 0 0 0.654902 0 0 0 1 0',
    bodyShadowMatrix: '0 0 0 0 0.0705882 0 0 0 0 0.14902 0 0 0 0 0.270588 0 0 0 1 0',
    headHighlightMatrix: '0 0 0 0 0.603922 0 0 0 0 0.760784 0 0 0 0 0.905882 0 0 0 1 0',
    headShadowMatrix: '0 0 0 0 0.0705882 0 0 0 0 0.14902 0 0 0 0 0.270588 0 0 0 1 0',
    armHighlightMatrix: '0 0 0 0 0.270588 0 0 0 0 0.447059 0 0 0 0 0.654902 0 0 0 1 0',
    armShadowMatrix: '0 0 0 0 0.0705882 0 0 0 0 0.14902 0 0 0 0 0.270588 0 0 0 1 0'
  },
  green: {
    bodyFill: '#5FA64F',
    neckShadowColor: '#2E5A24',
    bodyHighlightMatrix: '0 0 0 0 0.403922 0 0 0 0 0.654902 0 0 0 0 0.364706 0 0 0 1 0',
    bodyShadowMatrix: '0 0 0 0 0.113725 0 0 0 0 0.270588 0 0 0 0 0.117647 0 0 0 1 0',
    headHighlightMatrix: '0 0 0 0 0.780392 0 0 0 0 0.894118 0 0 0 0 0.733333 0 0 0 1 0',
    headShadowMatrix: '0 0 0 0 0.113725 0 0 0 0 0.270588 0 0 0 0 0.117647 0 0 0 1 0',
    armHighlightMatrix: '0 0 0 0 0.403922 0 0 0 0 0.654902 0 0 0 0 0.364706 0 0 0 1 0',
    armShadowMatrix: '0 0 0 0 0.113725 0 0 0 0 0.270588 0 0 0 0 0.117647 0 0 0 1 0'
  },
  skyBlue: {
    bodyFill: '#8ECAE6',
    neckShadowColor: '#4C829B',
    bodyHighlightMatrix: '0 0 0 0 0.81 0 0 0 0 0.92 0 0 0 0 0.97 0 0 0 1 0',
    bodyShadowMatrix: '0 0 0 0 0.2 0 0 0 0 0.5 0 0 0 0 0.65 0 0 0 1 0',
    headHighlightMatrix: '0 0 0 0 0.85 0 0 0 0 0.94 0 0 0 0 0.98 0 0 0 1 0',
    headShadowMatrix: '0 0 0 0 0.2 0 0 0 0 0.5 0 0 0 0 0.65 0 0 0 1 0',
    armHighlightMatrix: '0 0 0 0 0.81 0 0 0 0 0.92 0 0 0 0 0.97 0 0 0 1 0',
    armShadowMatrix: '0 0 0 0 0.231 0 0 0 0 0.533 0 0 0 0 0.675 0 0 0 1 0'
  }
};

let currentPalette = 'yellow';
let currentMode = 1; // 1 = Mode 1 (Yellow), 2 = Mode 2 (Sky Blue)

// Viseme shape scale mapping in X and Y
const VISEME_SHAPES = {
  'sil': { x: 0.9, y: 0.05 },
  'PP': { x: 0.8, y: 0.05 },
  'FF': { x: 0.85, y: 0.25 },
  'SS': { x: 0.95, y: 0.28 },
  'E': { x: 1.3, y: 0.5 },
  'ih': { x: 1.25, y: 0.45 },
  'aa': { x: 1.15, y: 1.05 },
  'oh': { x: 0.85, y: 1.1 },
  'ou': { x: 0.65, y: 0.85 }
};

let targetMouthScaleX = 1.0;
let targetMouthScaleY = 0.05;
let currentMouthScaleX = 1.0;
let currentMouthScaleY = 0.05;

// ──────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────

function lerp(start, end, amt) {
  return (1 - amt) * start + amt * end;
}

function easeInOutCubic(x) {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

function interpolateArray(val, input, output, easeFn) {
  if (val <= input[0]) return output[0];
  if (val >= input[input.length - 1]) return output[output.length - 1];
  for (let i = 0; i < input.length - 1; i++) {
    if (val >= input[i] && val <= input[i+1]) {
      const t = (val - input[i]) / (input[i+1] - input[i]);
      const easedT = easeFn ? easeFn(t) : t;
      return output[i] + easedT * (output[i+1] - output[i]);
    }
  }
  return output[0];
}

function toRiveVisemeCode(oculusCode) {
  const OCULUS_TO_RIVE_VISEME = {
    I: 'ih',
    O: 'oh',
    U: 'ou',
    e: 'E',
    i: 'ih',
    o: 'oh',
    u: 'ou',
  };
  return OCULUS_TO_RIVE_VISEME[oculusCode] || oculusCode;
}

// ──────────────────────────────────────────────────────────
// Color Controller
// ──────────────────────────────────────────────────────────

function updatePaletteColors(paletteName) {
  const p = PALETTES[paletteName];
  if (!p) return;

  const bodyPath = document.getElementById('body-path');
  const headDot = document.getElementById('head-dot');
  const leftArm = document.getElementById('left-arm');
  const rightArmWave = document.getElementById('right-arm-wave');
  const rightArmSteady = document.getElementById('right-arm-steady');
  
  if (bodyPath) bodyPath.setAttribute('fill', p.bodyFill);
  if (headDot) headDot.setAttribute('fill', p.bodyFill);
  if (leftArm) leftArm.setAttribute('fill', p.bodyFill);
  if (rightArmWave) rightArmWave.setAttribute('fill', p.bodyFill);
  if (rightArmSteady) rightArmSteady.setAttribute('fill', p.bodyFill);
  
  const bookLeftArm = document.getElementById('book-left-arm');
  const bookRightArm = document.getElementById('book-right-arm');
  const cupLeftArm = document.getElementById('cup-left-arm');
  const cupRightArm = document.getElementById('cup-right-arm');
  if (bookLeftArm) bookLeftArm.setAttribute('fill', p.bodyFill);
  if (bookRightArm) bookRightArm.setAttribute('fill', p.bodyFill);
  if (cupLeftArm) cupLeftArm.setAttribute('fill', p.bodyFill);
  if (cupRightArm) cupRightArm.setAttribute('fill', p.bodyFill);
  
  const neckShadow1 = document.querySelector('#neck-shadow-1 path');
  const neckShadow2 = document.querySelector('#neck-shadow-2 path');
  if (neckShadow1) neckShadow1.setAttribute('fill', p.neckShadowColor);
  if (neckShadow2) neckShadow2.setAttribute('fill', p.neckShadowColor);

  const f0Highlight = document.getElementById('f0-highlight-matrix');
  const f0Shadow = document.getElementById('f0-shadow-matrix');
  if (f0Highlight) f0Highlight.setAttribute('values', p.bodyHighlightMatrix);
  if (f0Shadow) f0Shadow.setAttribute('values', p.bodyShadowMatrix);
  
  const f1Highlight = document.getElementById('f1-highlight-matrix');
  const f1Shadow = document.getElementById('f1-shadow-matrix');
  if (f1Highlight) f1Highlight.setAttribute('values', p.headHighlightMatrix);
  if (f1Shadow) f1Shadow.setAttribute('values', p.headShadowMatrix);
  
  const f4Highlight = document.getElementById('f4-highlight-matrix');
  const f4Shadow = document.getElementById('f4-shadow-matrix');
  if (f4Highlight) f4Highlight.setAttribute('values', p.armHighlightMatrix);
  if (f4Shadow) f4Shadow.setAttribute('values', p.armShadowMatrix);
  
  const f5Highlight = document.getElementById('f5-highlight-matrix');
  const f5Shadow = document.getElementById('f5-shadow-matrix');
  const leftArmShadow = p.armShadowMatrix.endsWith(" 1 0") 
    ? p.armShadowMatrix.substring(0, p.armShadowMatrix.length - 4) + " 0.8 0"
    : p.armShadowMatrix;
  if (f5Highlight) f5Highlight.setAttribute('values', p.armHighlightMatrix);
  if (f5Shadow) f5Shadow.setAttribute('values', leftArmShadow);

  const f13Highlight = document.getElementById('f13-highlight-matrix');
  const f13Shadow = document.getElementById('f13-shadow-matrix');
  if (f13Highlight) f13Highlight.setAttribute('values', p.armHighlightMatrix);
  if (f13Shadow) f13Shadow.setAttribute('values', leftArmShadow);

  // Apply colors to dynamic custom SVG layers if active
  if (currentMascotSVGFile !== '') {
    const bobGroup = document.getElementById('bob-group');
    if (bobGroup) {
      const yellowElements = bobGroup.querySelectorAll('[fill="#F7D145"], [fill="#f7d145"], [fill="rgb(247, 209, 69)"]');
      yellowElements.forEach(el => el.setAttribute('fill', p.bodyFill));

      const shadowElements = bobGroup.querySelectorAll('[fill="#B23C05"], [fill="#b23c05"], [fill="rgb(178, 60, 5)"]');
      shadowElements.forEach(el => el.setAttribute('fill', p.neckShadowColor));
    }

    const mainDefs = document.querySelector('#mascot-svg defs');
    if (mainDefs) {
      const customMatrices = mainDefs.querySelectorAll('.custom-def feColorMatrix');
      customMatrices.forEach(matrix => {
        const vals = matrix.getAttribute('values');
        if (!vals) return;
        if (vals.includes('0.962384') || vals.includes('0.860378')) {
          matrix.setAttribute('values', p.bodyHighlightMatrix);
        } else if (vals.includes('0.797063') && (vals.includes('0.575703') || vals.includes('0.0980312'))) {
          matrix.setAttribute('values', p.bodyShadowMatrix);
        } else if (vals.startsWith('0 0 0 0 1') || vals.includes('1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 0 0 0 1 0')) {
          matrix.setAttribute('values', p.headHighlightMatrix);
        } else if (vals.includes('0.973501') || vals.includes('0.909066')) {
          matrix.setAttribute('values', p.armHighlightMatrix);
        } else if (vals.includes('0.796078') || vals.includes('0.576471')) {
          matrix.setAttribute('values', p.armShadowMatrix);
        }
      });
    }
  }
}

function updatePaletteMapping() {
  let target = (currentMode === 2) ? 'skyBlue' : 'yellow';
  
  if (currentState === 'angry' || currentState === 'error') {
    target = 'burgundy';
  } else if (currentState === 'sleeping') {
    target = 'navy';
  } else if (currentState === 'chilling') {
    const isSpeaking = visemeQueue.length > 0 || speechTimer > 0;
    if (isSpeaking) {
      target = (currentMode === 2) ? 'skyBlue' : 'yellow';
    } else {
      target = 'green';
    }
  }
  
  if (target !== currentPalette) {
    currentPalette = target;
    updatePaletteColors(currentPalette);
  }
}

// ──────────────────────────────────────────────────────────
// State Target Controller
// ──────────────────────────────────────────────────────────

function updateStateTargets() {
  updatePaletteMapping();

  // Load custom SVG or restore original based on current state
  const customSvg = MASCOT_STATE_SVGS[currentState];
  if (customSvg) {
    loadCustomMascotSVG(customSvg);
  } else {
    restoreOriginalMascot();
  }

  // Talking
  const isSpeaking = visemeQueue.length > 0 || speechTimer > 0;
  targetTalkingProgress = (currentState === 'talking' || isSpeaking) ? 1 : 0;

  // Sleeping
  targetSleepProgress = (currentState === 'sleeping') ? 1 : 0;

  // Thinking
  if (currentState === 'thinking' || currentState === 'confused' || currentState === 'concerned' || currentState === 'reading' || currentState === 'writing') {
    targetThinkProgress = 1;
  } else {
    targetThinkProgress = 0;
  }

  // Waving vs Steady arm
  if (['idle', 'chilling', 'waiting', 'sleeping', 'thinking', 'confused', 'concerned', 'reading', 'writing', 'drinking_coffee', 'drinking_boba'].includes(currentState)) {
    targetWavingProgress = 0;
    targetSteadyProgress = 1;
  } else {
    targetWavingProgress = 1;
    targetSteadyProgress = 0;
  }

  // Accessories progresses
  targetBookProgress = (currentState === 'reading' || currentState === 'writing') ? 1 : 0;
  targetCoffeeProgress = (currentState === 'drinking_coffee') ? 1 : 0;
  targetBobaProgress = (currentState === 'drinking_boba') ? 1 : 0;
}

function clearAckTimer() {
  if (ackTimer !== null) {
    clearTimeout(ackTimer);
    ackTimer = null;
  }
  isHoldingAckFace = false;
}

function holdThenIdle(ackFace, holdMs = ACK_FACE_HOLD_MS) {
  clearAckTimer();
  isHoldingAckFace = true;
  
  const tempState = mapFaceToState(ackFace);
  console.log(`[SVG Mascot Ack] Holding state "${tempState}" (from face "${ackFace}") for ${holdMs}ms`);
  
  currentState = tempState;
  stateTime = 0;
  updateStateTargets();
  
  ackTimer = setTimeout(() => {
    ackTimer = null;
    isHoldingAckFace = false;
    console.log('[SVG Mascot Ack] Hold complete, returning to idle');
    currentState = 'idle';
    stateTime = 0;
    updateStateTargets();
  }, holdMs);
}

function mapFaceToState(face) {
  const FACE_TO_STATE = {
    idle: 'idle',
    normal: 'idle',
    sleep: 'sleeping',
    listening: 'listening',
    thinking: 'thinking',
    confused: 'confused',
    speaking: 'talking',
    happy: 'happy',
    concerned: 'concerned',
    curious: 'thinking',
    proud: 'happy',
    cautious: 'thinking',
    celebrating: 'happy',
    writing: 'writing',
    reading: 'reading',
    recording: 'recording',
    waving: 'listening',
    dancing: 'happy',
    drinking_coffee: 'drinking_coffee',
    drinking_boba: 'drinking_boba'
  };
  return FACE_TO_STATE[face] || 'idle';
}

function pickConversationAckFace(text) {
  if (!text || !text.trim()) return null;
  
  const trimmed = text.trim();
  
  // Check for emoji reactions first
  for (const ch of trimmed) {
    if (CELEBRATING_REACTION_EMOJIS.has(ch)) return 'celebrating';
    if (DANCING_REACTION_EMOJIS.has(ch)) return 'dancing';
    if (WAVING_REACTION_EMOJIS.has(ch)) return 'waving';
    if (PROUD_REACTION_EMOJIS.has(ch)) return 'proud';
    if (HAPPY_REACTION_EMOJIS.has(ch)) return 'happy';
    if (CURIOUS_REACTION_EMOJIS.has(ch)) return 'curious';
    if (CONFUSED_REACTION_EMOJIS.has(ch)) return 'confused';
    if (CAUTIOUS_REACTION_EMOJIS.has(ch)) return 'cautious';
    if (CONCERNED_REACTION_EMOJIS.has(ch)) return 'concerned';
  }
  
  // Text keyword analysis
  if (CONCERNED_TEXT_RE.test(trimmed)) return 'concerned';
  if (CAUTIOUS_TEXT_RE.test(trimmed)) return 'cautious';
  if (CELEBRATING_TEXT_RE.test(trimmed)) return 'celebrating';
  if (PROUD_TEXT_RE.test(trimmed)) return 'proud';
  if (CONFUSED_TEXT_RE.test(trimmed)) return 'confused';
  if (CURIOUS_TEXT_RE.test(trimmed)) return 'curious';
  if (GREETING_TEXT_RE.test(trimmed)) return 'waving';
  if (HAPPY_TEXT_RE.test(trimmed)) return 'happy';
  
  return null;
}

// ──────────────────────────────────────────────────────────
// Viseme / Speech Controller
// ──────────────────────────────────────────────────────────

function generateVisemesFromText(text) {
  if (!text) return [];
  
  const words = text.toLowerCase()
    .replace(/[.,\/#!$%\^&\*;:{}=\-_`~()?]/g, "")
    .split(/\s+/)
    .filter(w => w.length > 0);
    
  const queue = [];
  
  for (const word of words) {
    const wordDuration = Math.max(200, Math.min(750, word.length * 90)) / 1000;
    
    const keySounds = [];
    for (let i = 0; i < word.length; i++) {
      const ch = word[i];
      if (ch === 'a') keySounds.push('aa');
      else if (ch === 'o') keySounds.push('oh');
      else if (ch === 'u' || ch === 'w') keySounds.push('ou');
      else if (ch === 'e') keySounds.push('E');
      else if (ch === 'i' || ch === 'y') keySounds.push('ih');
      else if (ch === 'p' || ch === 'b' || ch === 'm') keySounds.push('PP');
      else if (ch === 'f' || ch === 'v') keySounds.push('FF');
      else if (['s', 'c', 'z', 'x', 't', 'd', 'n', 'l', 'g', 'k', 'j', 'q', 'r'].includes(ch)) keySounds.push('SS');
    }
    
    const filteredSounds = [];
    for (const sound of keySounds) {
      if (filteredSounds.length === 0 || filteredSounds[filteredSounds.length - 1] !== sound) {
        filteredSounds.push(sound);
      }
    }
    
    const finalSounds = filteredSounds.slice(0, 4);
    
    if (finalSounds.length === 0) {
      queue.push({ code: 'ih', duration: wordDuration * 0.6 });
      queue.push({ code: 'sil', duration: wordDuration * 0.4 });
      continue;
    }
    
    const frameDuration = wordDuration / finalSounds.length;
    for (const sound of finalSounds) {
      queue.push({ code: sound, duration: frameDuration });
    }
    
    queue.push({ code: 'sil', duration: 0.03 });
  }
  
  return queue;
}

export function setSpeechText(text) {
  visemeQueue = generateVisemesFromText(text);
  speechTimer = 0; 
  console.log('[SVG lipsync] Viseme queue length:', visemeQueue.length);
  
  if (text && !text.startsWith("Heard: ")) {
    accumulatedSpeechForAck += " " + text;
  }
}

export function onSpeechDone() {
  const ackFace = pickConversationAckFace(accumulatedSpeechForAck);
  console.log(`[SVG Ack] Speech done. Accumulated text: "${accumulatedSpeechForAck.trim().substring(0, 80)}..." -> ackFace: ${ackFace || 'happy (default)'}`);
  
  lastVisemeSetTime = performance.now();
  lastVisemeCode = 'sil';
  
  holdThenIdle(ackFace || 'happy');
  
  accumulatedSpeechForAck = "";
  thinkingRoundCount = 0;
}

export function onErrorOccurred() {
  console.log('[SVG Ack] Error occurred, showing concerned face');
  holdThenIdle('concerned');
  accumulatedSpeechForAck = "";
}

// ──────────────────────────────────────────────────────────
// Initialization
// ──────────────────────────────────────────────────────────

export function initSVG(containerId) {
  console.log('[SVG Mascot] Initializing SVG elements & loops...');
  startTime = performance.now();
  lastTimestamp = startTime;

  // Cache original bob-group HTML for restoring
  const bobGroup = document.getElementById('bob-group');
  if (bobGroup) {
    originalBobGroupHTML = bobGroup.innerHTML;
  }

  // Set default color theme
  updatePaletteColors('yellow');

  // Start frame loop
  isAnimating = true;
  requestAnimationFrame(animate);
}

async function loadCustomMascotSVG(fileName) {
  if (currentMascotSVGFile === fileName) return;
  currentMascotSVGFile = fileName;

  console.log(`[SVG Mascot] Loading custom pose: ${fileName}`);
  try {
    const response = await fetch(`assets/mascot/${fileName}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch SVG: ${response.statusText}`);
    }
    const svgText = await response.text();

    const parser = new DOMParser();
    const doc = parser.parseFromString(svgText, 'image/svg+xml');
    const customSvg = doc.querySelector('svg');

    if (!customSvg) return;

    // Get new defs
    const defs = customSvg.querySelector('defs');
    
    // Clean up any previously added custom defs
    const mainDefs = document.querySelector('#mascot-svg defs');
    if (mainDefs) {
      const oldCustomDefs = mainDefs.querySelectorAll('.custom-def');
      oldCustomDefs.forEach(el => el.remove());

      if (defs) {
        // Mark them as custom so we can clean them up later
        Array.from(defs.children).forEach(child => {
          child.classList.add('custom-def');
          mainDefs.appendChild(child);
        });
      }
    }

    // Replace content of bob-group with character paths
    const bobGroup = document.getElementById('bob-group');
    if (bobGroup) {
      const characterElements = Array.from(customSvg.children).filter(el => {
        return el.tagName !== 'defs' && !(el.tagName === 'rect' && el.getAttribute('width') === '1000');
      });

      bobGroup.innerHTML = '';
      characterElements.forEach(el => {
        bobGroup.appendChild(el.cloneNode(true));
      });
    }

    // Re-apply palette colors to the newly loaded paths
    updatePaletteColors(currentPalette);
  } catch (err) {
    console.error(`[SVG Mascot] Error loading custom pose ${fileName}:`, err);
  }
}

function restoreOriginalMascot() {
  if (currentMascotSVGFile === '') return;
  console.log('[SVG Mascot] Restoring original animated mascot...');
  currentMascotSVGFile = '';

  const mainDefs = document.querySelector('#mascot-svg defs');
  if (mainDefs) {
    const oldCustomDefs = mainDefs.querySelectorAll('.custom-def');
    oldCustomDefs.forEach(el => el.remove());
  }

  const bobGroup = document.getElementById('bob-group');
  if (bobGroup && originalBobGroupHTML) {
    bobGroup.innerHTML = originalBobGroupHTML;
  }

  // Re-apply palette colors
  updatePaletteColors(currentPalette);
}

export function setMascotMode(mode) {
  currentMode = mode;
  console.log(`[SVG Mascot Mode] Mode set to: ${currentMode}`);
  updatePaletteMapping();
}

export function setMascotState(state) {
  if (currentState === state) return;
  
  // Clear ack state if we move to a new action explicitly
  if (isHoldingAckFace && state !== 'idle') {
    clearAckTimer();
  }

  previousState = currentState;
  currentState = state;
  stateTime = 0;
  console.log(`[SVG State] ${previousState} -> ${currentState}`);
  
  // Reset speech states
  if (currentState !== 'talking') {
    visemeQueue = [];
    lastVisemeCode = 'sil';
    const talkingMouthGroup = document.getElementById('talking-mouth-group');
    const normalMouthGroup = document.getElementById('normal-mouth-group');
    if (talkingMouthGroup) talkingMouthGroup.style.display = 'none';
    if (normalMouthGroup) {
      normalMouthGroup.style.display = 'block';
      normalMouthGroup.setAttribute('opacity', 1);
    }
  }

  // Conversational ack face routing
  if (previousState === 'talking' && (state === 'idle' || state === 'thinking')) {
    onSpeechDone();
    if (state === 'thinking') {
      thinkingRoundCount++;
    }
    return; 
  }

  if (previousState === 'error' && state === 'idle') {
    onErrorOccurred();
    return;
  }
  
  if (state === 'thinking') {
    thinkingRoundCount++;
    if (thinkingRoundCount > 2) {
      currentState = 'drinking_coffee'; // Map to coffee drinking state when thinking too long
    }
  }

  if (state === 'listening' || state === 'idle') {
    thinkingRoundCount = 0;
  }

  if (state === 'happy' || state === 'praise' || state === 'excited' || state === 'celebrating') {
    clearAckTimer();
    holdThenIdle(state === 'celebrating' ? 'celebrating' : 'happy', 1500);
    return;
  }

  if (state === 'startup') {
    clearAckTimer();
    holdThenIdle('waving', 2000);
    return;
  }

  updateStateTargets();
}

// ──────────────────────────────────────────────────────────
// Render Loop
// ──────────────────────────────────────────────────────────

function animate(timestamp) {
  if (!isAnimating) return;
  requestAnimationFrame(animate);

  // Self-healing NaN sanity checks
  if (isNaN(currentThinkProgress)) currentThinkProgress = 0;
  if (isNaN(targetThinkProgress)) targetThinkProgress = 0;
  if (isNaN(currentSleepProgress)) currentSleepProgress = 0;
  if (isNaN(targetSleepProgress)) targetSleepProgress = 0;
  if (isNaN(currentTalkingProgress)) currentTalkingProgress = 0;
  if (isNaN(targetTalkingProgress)) targetTalkingProgress = 0;
  if (isNaN(currentWavingProgress)) currentWavingProgress = 1;
  if (isNaN(targetWavingProgress)) targetWavingProgress = 1;
  if (isNaN(currentSteadyProgress)) currentSteadyProgress = 0;
  if (isNaN(targetSteadyProgress)) targetSteadyProgress = 0;
  if (isNaN(currentBookProgress)) currentBookProgress = 0;
  if (isNaN(targetBookProgress)) targetBookProgress = 0;
  if (isNaN(currentCoffeeProgress)) currentCoffeeProgress = 0;
  if (isNaN(targetCoffeeProgress)) targetCoffeeProgress = 0;
  if (isNaN(currentBobaProgress)) currentBobaProgress = 0;
  if (isNaN(targetBobaProgress)) targetBobaProgress = 0;

  if (isNaN(currentMouthScaleX)) currentMouthScaleX = 1.0;
  if (isNaN(targetMouthScaleX)) targetMouthScaleX = 1.0;
  if (isNaN(currentMouthScaleY)) currentMouthScaleY = 0.05;
  if (isNaN(targetMouthScaleY)) targetMouthScaleY = 0.05;

  if (isNaN(startTime)) startTime = performance.now();
  if (isNaN(lastTimestamp)) lastTimestamp = performance.now();
  if (isNaN(stateTime)) stateTime = 0;

  const rawDt = (timestamp - lastTimestamp) / 1000;
  const dt = (isNaN(rawDt) || rawDt < 0) ? 0 : rawDt;
  lastTimestamp = (isNaN(timestamp) || !timestamp) ? performance.now() : timestamp;

  // Clamp dt to avoid huge lag steps when window is minimized or out of focus
  const clampedDt = Math.max(0, Math.min(dt, 0.1));
  stateTime += clampedDt;

  let t = (performance.now() - startTime) / 1000;
  if (isNaN(t)) t = 0;

  // Framerate independent LERP progress variables
  const lerpSpeed = 10; 
  let lerpFactor = 1 - Math.exp(-lerpSpeed * clampedDt);
  if (isNaN(lerpFactor)) lerpFactor = 0.15;

  currentThinkProgress += (targetThinkProgress - currentThinkProgress) * lerpFactor;
  currentSleepProgress += (targetSleepProgress - currentSleepProgress) * lerpFactor;
  currentTalkingProgress += (targetTalkingProgress - currentTalkingProgress) * lerpFactor;
  currentWavingProgress += (targetWavingProgress - currentWavingProgress) * lerpFactor;
  currentSteadyProgress += (targetSteadyProgress - currentSteadyProgress) * lerpFactor;
  currentBookProgress += (targetBookProgress - currentBookProgress) * lerpFactor;
  currentCoffeeProgress += (targetCoffeeProgress - currentCoffeeProgress) * lerpFactor;
  currentBobaProgress += (targetBobaProgress - currentBobaProgress) * lerpFactor;

  // DOM node lookups
  const bobGroup = document.getElementById('bob-group');
  const headDotGroup = document.getElementById('head-dot-group');
  const leftArmGroup = document.getElementById('left-arm-group');
  const rightArmWaveGroup = document.getElementById('right-arm-wave-group');
  const rightArmSteadyGroup = document.getElementById('right-arm-steady-group');
  const groundShadowGroup = document.getElementById('ground-shadow-group');
  const faceGroup = document.getElementById('face-group');
  const awakeEyesGroup = document.getElementById('awake-eyes-group');
  const leftEyeScaleGroup = document.getElementById('left-eye-scale-group');
  const rightEyeScaleGroup = document.getElementById('right-eye-scale-group');
  const sleepEyesGroup = document.getElementById('sleep-eyes-group');
  const normalMouthGroup = document.getElementById('normal-mouth-group');
  const thinkingMouth = document.getElementById('thinking-mouth');
  const talkingMouthGroup = document.getElementById('talking-mouth-group');
  const tongue = document.getElementById('tongue');
  const tongueHighlight = document.getElementById('tongue-highlight');
  const zzzGroup = document.getElementById('zzz-group');
  
  const accessoryArmsGroup = document.getElementById('accessory-arms-group');
  const bookArms = document.getElementById('book-arms');
  const cupArms = document.getElementById('cup-arms');
  const bookLeftArmRotateGroup = document.getElementById('book-left-arm-rotate-group');
  const bookRightArmRotateGroup = document.getElementById('book-right-arm-rotate-group');
  const cupLeftArmRotateGroup = document.getElementById('cup-left-arm-rotate-group');
  const cupRightArmRotateGroup = document.getElementById('cup-right-arm-rotate-group');
  
  const bookAccessoryGroup = document.getElementById('book-accessory-group');
  const bookRotateGroup = document.getElementById('book-rotate-group');
  const coffeeCupAccessoryGroup = document.getElementById('coffee-cup-accessory-group');
  const coffeeCupRotateGroup = document.getElementById('coffee-cup-rotate-group');
  const bobaCupAccessoryGroup = document.getElementById('boba-cup-accessory-group');
  const bobaCupRotateGroup = document.getElementById('boba-cup-rotate-group');

  if (!bobGroup) return;

  // 1. Vertical Bobbing
  const bob = Math.sin(t * Math.PI * 1.2) * 14;
  bobGroup.setAttribute('transform', `translate(0, ${bob})`);

  // Ground shadow scaling
  if (groundShadowGroup) {
    const shadowScale = 1 - bob / 600;
    groundShadowGroup.setAttribute('transform', `translate(500, 975) scale(${shadowScale}, 1)`);
  }

  // 2. Head Dot independent drift
  if (headDotGroup) {
    const dotPhase = t * Math.PI * 1.0;
    const dotDx = Math.sin(dotPhase * 0.7) * 6;
    const dotDy = Math.sin(dotPhase) * 9;
    const press = Math.max(0, Math.sin(dotPhase));
    const dotSquashY = 1 - 0.08 * press;
    const dotSquashX = 1 + 0.05 * press;
    headDotGroup.setAttribute('transform', `translate(${dotDx}, ${dotDy}) translate(493, 145) scale(${dotSquashX}, ${dotSquashY}) translate(-493, -145)`);
  }

  // 3. Eyelids Blinking & Sleep
  const blinkPeriod = 2.6;
  const blinkOffset = 1.3;
  const inBlink = ((t + blinkOffset) % blinkPeriod) < 0.2; 
  const blinkScale = inBlink ? 0.12 : 1.0;

  const eyeScaleY = lerp(blinkScale, 0.0, currentSleepProgress);
  const showSleepEyes = currentSleepProgress > 0.95;

  if (showSleepEyes) {
    if (awakeEyesGroup) awakeEyesGroup.style.display = 'none';
    if (sleepEyesGroup) sleepEyesGroup.style.display = 'block';
  } else {
    if (awakeEyesGroup) awakeEyesGroup.style.display = 'block';
    if (sleepEyesGroup) sleepEyesGroup.style.display = 'none';
    if (leftEyeScaleGroup) leftEyeScaleGroup.setAttribute('transform', `translate(411, 465) scale(1, ${eyeScaleY}) translate(-411, -465)`);
    if (rightEyeScaleGroup) rightEyeScaleGroup.setAttribute('transform', `translate(589, 465) scale(1, ${eyeScaleY}) translate(-589, -465)`);
  }

  // 4. Arm Swaying & waving
  // Determine accessory blend
  const anyAccessoryProgress = Math.min(1.0, currentBookProgress + currentCoffeeProgress + currentBobaProgress);
  const normalArmsOpacity = 1.0 - anyAccessoryProgress;

  // Left arm sway & Pondering hand near chin
  if (leftArmGroup) {
    const leftSway = Math.sin(t * Math.PI * 1.6) * 7;
    const thinkArmOscillate = (currentThinkProgress > 0.95) ? Math.sin(t * Math.PI * 0.5) * 2 : 0;
    const leftArmAngle = lerp(leftSway, -128 + thinkArmOscillate, currentThinkProgress);
    leftArmGroup.setAttribute('transform', `rotate(${leftArmAngle}, 290, 700)`);
    leftArmGroup.setAttribute('opacity', normalArmsOpacity);
    leftArmGroup.style.display = normalArmsOpacity > 0.01 ? 'block' : 'none';
  }

  // Right arm waving
  const wavePeriod = 2.4;
  const waveTime = t % wavePeriod;
  const waveInputTimes = [0, 2.4 * 0.12, 2.4 * 0.25, 2.4 * 0.38, 2.4 * 0.50, 2.4 * 0.62, 2.4 * 0.75, 2.4];
  const waveOutputAngles = [0, -9, 0, -7, 0, -5, 0, 0];
  const waveAngle = interpolateArray(waveTime, waveInputTimes, waveOutputAngles, easeInOutCubic);

  // Right arm steady sway
  const steadySway = Math.sin(t * Math.PI * 1.6 + 0.3) * 6;

  if (rightArmWaveGroup) {
    const opacity = currentWavingProgress * normalArmsOpacity;
    if (opacity > 0.01) {
      rightArmWaveGroup.style.display = 'block';
      rightArmWaveGroup.setAttribute('transform', `rotate(${waveAngle}, 776, 568)`);
      rightArmWaveGroup.setAttribute('opacity', opacity);
    } else {
      rightArmWaveGroup.style.display = 'none';
    }
  }

  if (rightArmSteadyGroup) {
    const opacity = currentSteadyProgress * normalArmsOpacity;
    if (opacity > 0.01) {
      rightArmSteadyGroup.style.display = 'block';
      rightArmSteadyGroup.setAttribute('transform', `rotate(${steadySway}, 655, 709)`);
      rightArmSteadyGroup.setAttribute('opacity', opacity);
    } else {
      rightArmSteadyGroup.style.display = 'none';
    }
  }

  // 5. Head tilt & eye drift
  if (faceGroup) {
    const headTilt = lerp(0, -4.5 + Math.sin(t * Math.PI * 0.38) * 1.8, currentThinkProgress);
    faceGroup.setAttribute('transform', `rotate(${headTilt}, 495, 375)`);
  }
  if (awakeEyesGroup) {
    const thinkEyeX = currentThinkProgress * -6;
    const thinkEyeY = currentThinkProgress * -9;
    awakeEyesGroup.setAttribute('transform', `translate(${thinkEyeX}, ${thinkEyeY})`);
  }

  // Accessory Arms & Items Animations
  if (accessoryArmsGroup) {
    if (anyAccessoryProgress > 0.01) {
      accessoryArmsGroup.style.display = 'block';
      accessoryArmsGroup.setAttribute('opacity', anyAccessoryProgress);
      
      // Determine which sub-arms to show
      if (currentBookProgress > 0.01) {
        if (bookArms) bookArms.style.display = 'block';
        if (cupArms) cupArms.style.display = 'none';
        
        // Sway book reading arms
        const bookSway = Math.sin(t * Math.PI * 0.4) * 2.8;
        const leftArmSway = bookSway * 0.75;
        const rightArmSway = bookSway * 0.6;
        
        if (bookLeftArmRotateGroup) bookLeftArmRotateGroup.setAttribute('transform', `rotate(${leftArmSway}, 313, 640)`);
        if (bookRightArmRotateGroup) bookRightArmRotateGroup.setAttribute('transform', `rotate(${rightArmSway}, 553, 682)`);
      } else {
        if (bookArms) bookArms.style.display = 'none';
        if (cupArms) cupArms.style.display = 'block';
        
        // Sway cup holding arms
        const cupLeftArmAngle = Math.sin(t * Math.PI * 0.8) * 6;
        const cupRightArmAngle = Math.sin(t * Math.PI * 0.8 + Math.PI) * 6;
        
        if (cupLeftArmRotateGroup) cupLeftArmRotateGroup.setAttribute('transform', `rotate(${cupLeftArmAngle}, 320, 658)`);
        if (cupRightArmRotateGroup) cupRightArmRotateGroup.setAttribute('transform', `rotate(${cupRightArmAngle}, 636, 655)`);
      }
    } else {
      accessoryArmsGroup.style.display = 'none';
    }
  }

  // Accessories display
  if (bookAccessoryGroup) {
    if (currentBookProgress > 0.01) {
      bookAccessoryGroup.style.display = 'block';
      bookAccessoryGroup.setAttribute('opacity', currentBookProgress);
      const bookSway = Math.sin(t * Math.PI * 0.4) * 2.8;
      if (bookRotateGroup) bookRotateGroup.setAttribute('transform', `rotate(${bookSway}, 480, 665)`);
    } else {
      bookAccessoryGroup.style.display = 'none';
    }
  }

  if (coffeeCupAccessoryGroup) {
    if (currentCoffeeProgress > 0.01) {
      coffeeCupAccessoryGroup.style.display = 'block';
      coffeeCupAccessoryGroup.setAttribute('opacity', currentCoffeeProgress);
      const cupSway = Math.sin(t * Math.PI * 0.9) * 2.5;
      if (coffeeCupRotateGroup) coffeeCupRotateGroup.setAttribute('transform', `rotate(${cupSway}, 500, 610)`);
    } else {
      coffeeCupAccessoryGroup.style.display = 'none';
    }
  }

  if (bobaCupAccessoryGroup) {
    if (currentBobaProgress > 0.01) {
      bobaCupAccessoryGroup.style.display = 'block';
      bobaCupAccessoryGroup.setAttribute('opacity', currentBobaProgress);
      const cupSway = Math.sin(t * Math.PI * 0.9) * 2.5;
      if (bobaCupRotateGroup) bobaCupRotateGroup.setAttribute('transform', `rotate(${cupSway}, 490, 660)`);
    } else {
      bobaCupAccessoryGroup.style.display = 'none';
    }
  }

  // 6. Mouth & lipsync
  const mouthOpacity = Math.max(0, 1 - currentThinkProgress - currentTalkingProgress);
  if (normalMouthGroup) normalMouthGroup.setAttribute('opacity', mouthOpacity);
  
  if (thinkingMouth) {
    if (currentThinkProgress > 0.05) {
      thinkingMouth.style.display = 'block';
      thinkingMouth.setAttribute('opacity', currentThinkProgress);
    } else {
      thinkingMouth.style.display = 'none';
    }
  }

  if (talkingMouthGroup) {
    if (currentTalkingProgress > 0.05) {
      talkingMouthGroup.style.display = 'block';
      talkingMouthGroup.setAttribute('opacity', currentTalkingProgress);

      let mouthOpenX = 1.0;
      let mouthOpenY = 0.05;
      const isSpeaking = visemeQueue.length > 0 || speechTimer > 0;
      
      if (isSpeaking) {
        if (speechTimer > 0) {
          speechTimer -= clampedDt;
        }
        if (speechTimer <= 0 && visemeQueue.length > 0) {
          const frame = visemeQueue.shift();
          if (frame) {
            const code = toRiveVisemeCode(frame.code);
            speechTimer = frame.duration;
            lastVisemeCode = code;
            lastVisemeSetTime = performance.now();
          }
        }
        
        const shape = VISEME_SHAPES[lastVisemeCode] || VISEME_SHAPES['sil'];
        mouthOpenX = shape.x;
        mouthOpenY = shape.y;
      } else {
        const talkA = Math.abs(Math.sin(t * Math.PI * 3.0));
        const talkB = Math.abs(Math.sin(t * Math.PI * 4.6 + 1.2));
        const rawY = Math.max(talkA, talkB * 0.8) * 0.95 + 0.05;
        mouthOpenY = rawY;
        mouthOpenX = 1.0 + (rawY * 0.1);
        
        if (lastVisemeCode !== 'sil') {
          const sinceLastViseme = performance.now() - lastVisemeSetTime;
          if (sinceLastViseme >= VISEME_DECAY_MS) {
            lastVisemeCode = 'sil';
          }
        }
      }

      const mouthLerpSpeed = 26;
      let mouthLerpFactor = 1 - Math.exp(-mouthLerpSpeed * clampedDt);
      if (isNaN(mouthLerpFactor)) mouthLerpFactor = 0.35;

      currentMouthScaleX += (mouthOpenX - currentMouthScaleX) * mouthLerpFactor;
      currentMouthScaleY += (mouthOpenY - currentMouthScaleY) * mouthLerpFactor;

      talkingMouthGroup.setAttribute('transform', `translate(495, 508) scale(${currentMouthScaleX}, ${currentMouthScaleY}) translate(-495, -508)`);
      
      const tongueOpacity = Math.min(1, Math.max(0, (currentMouthScaleY - 0.15) / 0.35));
      if (tongue) tongue.setAttribute('opacity', tongueOpacity);
      if (tongueHighlight) tongueHighlight.setAttribute('opacity', tongueOpacity * 0.85);
    } else {
      talkingMouthGroup.style.display = 'none';
    }
  }

  // 7. Sleep Zzz floating
  if (zzzGroup) {
    const isAsleep = currentSleepProgress > 0.98;
    if (isAsleep) {
      zzzGroup.style.display = 'block';
      const elapsedSinceSleep = stateTime;
      
      const updateZ = (el, delay) => {
        if (!el) return;
        const startAt = delay;
        if (elapsedSinceSleep < startAt) {
          el.setAttribute('opacity', 0);
          return;
        }
        const cycleTime = (elapsedSinceSleep - startAt) % 2.2;
        const progress = cycleTime / 2.2;
        const x = progress * 20;
        const y = -progress * 120;
        const opacity = interpolateArray(progress, [0, 0.1, 0.72, 1], [0, 1, 0.85, 0]);
        
        el.setAttribute('transform', `translate(${x}, ${y})`);
        el.setAttribute('opacity', opacity);
      };

      updateZ(document.getElementById('z1'), 0);
      updateZ(document.getElementById('z2'), 0.72);
      updateZ(document.getElementById('z3'), 1.44);
    } else {
      zzzGroup.style.display = 'none';
    }
  }
}
