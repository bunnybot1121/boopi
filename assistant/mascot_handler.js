// Rive-based mascot handler for Compy UI / boopi assistant.
// Plays tiny_mascot.riv directly inside Electron using @rive-app/canvas.
//
// Ported behavioral layer from OpenHumans project:
//   - Conversation-aware acknowledgment face picker (emoji + keyword analysis)
//   - Hold-then-idle transition pattern
//   - Tool-activity face mapping
//   - Smooth viseme decay
//   - Rich state transitions

const fs = require('fs');
const path = require('path');

let container = null;
let canvas = null;
let riveInstance = null;
let currentState = 'idle';
let previousState = 'idle';
let stateTime = 0;
let lastTime = 0;

// Rive view model properties
let poseProp = null;
let visemeProp = null;
let primaryColorProp = null;
let secondaryColorProp = null;

// ──────────────────────────────────────────────────────────
// Hold-then-idle transition system
// ──────────────────────────────────────────────────────────
const ACK_FACE_HOLD_MS = 700;    // How long to hold an ack face before returning to idle
const VISEME_DECAY_MS = 180;     // How long mouth takes to decay to silence after speech ends

let ackTimer = null;
let isHoldingAckFace = false;    // True while an ack face is being held

function clearAckTimer() {
  if (ackTimer !== null) {
    clearTimeout(ackTimer);
    ackTimer = null;
  }
  isHoldingAckFace = false;
}

/**
 * Show an acknowledgment face briefly, then return to idle.
 * This creates the "emotional beat" after a completed turn.
 */
function holdThenIdle(ackFace, holdMs = ACK_FACE_HOLD_MS) {
  clearAckTimer();
  isHoldingAckFace = true;
  
  const poseName = FACE_TO_POSE[ackFace] || 'idle';
  console.log(`[Rive Ack] Holding face "${ackFace}" (pose: ${poseName}) for ${holdMs}ms before returning to idle`);
  
  if (poseProp) {
    try {
      setEnumProperty(poseProp, poseName);
    } catch (e) {
      console.error('[Rive Ack] Error setting ack pose:', e);
    }
  }
  
  ackTimer = setTimeout(() => {
    ackTimer = null;
    isHoldingAckFace = false;
    console.log('[Rive Ack] Hold complete, returning to idle');
    if (poseProp) {
      try {
        setEnumProperty(poseProp, 'idle');
      } catch (e) {
        console.error('[Rive Ack] Error returning to idle:', e);
      }
    }
  }, holdMs);
}

// ──────────────────────────────────────────────────────────
// Conversation acknowledgment face picker
// (Ported from OpenHumans useHumanMascot.ts pickConversationAckFace)
// ──────────────────────────────────────────────────────────

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

/**
 * Analyze speech text to pick an appropriate acknowledgment face.
 * Checks emojis first (explicit signal), then falls back to keyword matching.
 * @param {string} text - The speech/response text to analyze
 * @returns {string|null} A MascotFace string or null if no match
 */
function pickConversationAckFace(text) {
  if (!text || !text.trim()) return null;
  
  const trimmed = text.trim();
  
  // Check for emoji reactions first (strongest signal)
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
  
  // Text keyword analysis — priority: concerned > cautious > proud > confused > curious > happy
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
// Color Utilities
// ──────────────────────────────────────────────────────────

function hexToArgbInt(hex) {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return ((0xff << 24) | (r << 16) | (g << 8) | b) >>> 0;
}

// ──────────────────────────────────────────────────────────
// Rive Property Helpers
// ──────────────────────────────────────────────────────────

function setEnumProperty(prop, stringValue) {
  if (!prop) return;
  try {
    prop.value = stringValue; // String representation is expected by Rive Web assembly bindings
  } catch (e) {
    console.error(`[Rive VM Debug] Error setting property to ${stringValue}:`, e);
  }
}

// ──────────────────────────────────────────────────────────
// Viseme System
// ──────────────────────────────────────────────────────────

// Pick Oculus 15-set viseme code from a character
function pickVisemeCode(ch) {
  switch (ch) {
    case 'a': return 'aa';
    case 'e': return 'E';
    case 'i':
    case 'y': return 'I';
    case 'o': return 'O';
    case 'u':
    case 'w': return 'U';
    case 'm':
    case 'b':
    case 'p': return 'PP';
    case 'f':
    case 'v': return 'FF';
    case 's':
    case 'z': return 'SS';
    case 'n':
    case 'l': return 'nn';
    case 't':
    case 'd': return 'DD';
    case 'k':
    case 'g': return 'kk';
    case 'r': return 'RR';
    default: return 'E';
  }
}

// Map Oculus 15-set viseme codes to Rive asset's viseme vocabulary
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

let mouthTimer = 0;
const talkingVisemes = ['aa', 'ih', 'E', 'oh', 'ou', 'PP', 'FF', 'SS', 'sil'];

// Procedural syllable-based lipsync state
let visemeQueue = [];
let speechTimer = 0;
let lastVisemeSetTime = 0;  // For decay tracking
let lastVisemeCode = 'sil'; // Last viseme set, for decay

// Accumulated speech for ack-face analysis
let accumulatedSpeechForAck = "";
let thinkingRoundCount = 0;  // Track consecutive thinking rounds

/**
 * Procedural syllable-based lip-sync parser.
 * Maps words to phoneme-like mouth shapes and schedules durations
 * based on word lengths, producing natural, flowing mouth movements.
 */
function generateVisemesFromText(text) {
  if (!text) return [];
  
  // Split into words, removing punctuation
  const words = text.toLowerCase()
    .replace(/[.,\/#!$%\^&\*;:{}=\-_`~()?]/g, "")
    .split(/\s+/)
    .filter(w => w.length > 0);
    
  const queue = [];
  
  for (const word of words) {
    // Estimate word duration based on character length:
    // 90ms per character, clamped between 200ms and 750ms
    const wordDuration = Math.max(200, Math.min(750, word.length * 90)) / 1000; // in seconds
    
    // Extract key phonetic elements (vowels and mouth-closing consonants only)
    const keySounds = [];
    for (let i = 0; i < word.length; i++) {
      const ch = word[i];
      if (ch === 'a') keySounds.push('aa');
      else if (ch === 'o') keySounds.push('oh');
      else if (ch === 'u' || ch === 'w') keySounds.push('ou');
      else if (ch === 'e' || ch === 'i' || ch === 'y') keySounds.push('ih');
      else if (ch === 'p' || ch === 'b' || ch === 'm') keySounds.push('PP');
      else if (ch === 'f' || ch === 'v') keySounds.push('FF');
    }
    
    // De-duplicate consecutive identical visemes
    const filteredSounds = [];
    for (const sound of keySounds) {
      if (filteredSounds.length === 0 || filteredSounds[filteredSounds.length - 1] !== sound) {
        filteredSounds.push(sound);
      }
    }
    
    // Limit to maximum of 3 mouth shapes per word to avoid rapid fluttering
    const finalSounds = filteredSounds.slice(0, 3);
    
    // Default open-close if no key sounds
    if (finalSounds.length === 0) {
      queue.push({ code: 'ih', duration: wordDuration * 0.6 });
      queue.push({ code: 'sil', duration: wordDuration * 0.4 });
      continue;
    }
    
    // Distribute duration
    const frameDuration = wordDuration / finalSounds.length;
    for (const sound of finalSounds) {
      queue.push({ code: sound, duration: frameDuration });
    }
    
    // Short silence between words for visual phrasing
    queue.push({ code: 'sil', duration: 0.03 });
  }
  
  return queue;
}

export function setSpeechText(text) {
  visemeQueue = generateVisemesFromText(text);
  speechTimer = 0; // Trigger immediate play of first frame
  console.log('[Rive Lipsync] Generated syllable-based viseme queue. Length:', visemeQueue.length);
  
  // Accumulate raw text for ack-face analysis
  if (text && !text.startsWith("Heard: ")) {
    accumulatedSpeechForAck += " " + text;
  }
}

/**
 * Called when speech playback is done (talking → idle transition).
 * Analyzes accumulated speech text and shows an appropriate ack face.
 */
export function onSpeechDone() {
  const ackFace = pickConversationAckFace(accumulatedSpeechForAck);
  console.log(`[Rive Ack] Speech done. Accumulated text: "${accumulatedSpeechForAck.trim().substring(0, 80)}..." → ackFace: ${ackFace || 'happy (default)'}`);
  
  // Reset viseme to silence smoothly
  lastVisemeSetTime = performance.now();
  lastVisemeCode = 'sil';
  
  // Show ack face, defaulting to 'happy'
  holdThenIdle(ackFace || 'happy');
  
  // Reset accumulated speech
  accumulatedSpeechForAck = "";
  thinkingRoundCount = 0;
}

/**
 * Called when an error transition occurs.
 * Shows concerned face briefly before idle.
 */
export function onErrorOccurred() {
  console.log('[Rive Ack] Error occurred, showing concerned face');
  holdThenIdle('concerned');
  accumulatedSpeechForAck = "";
}

// ──────────────────────────────────────────────────────────
// Pose Mapping (matches OpenHumans RiveMascot.tsx FACE_TO_POSE)
// ──────────────────────────────────────────────────────────

const FACE_TO_POSE = {
  idle: 'idle',
  normal: 'idle',
  sleep: 'idle',
  listening: 'idle',
  thinking: 'thinking',
  confused: 'thinking',
  speaking: 'idle',
  happy: 'idle',
  concerned: 'thinking',
  curious: 'bookreading',
  proud: 'celebration',
  cautious: 'thinking',
  celebrating: 'celebration',
  writing: 'writing',
  reading: 'bookreading',
  recording: 'recording',
  waving: 'hand_wave',
  dancing: 'dancing',
  drinking_coffee: 'coffeedrink',
  drinking_boba: 'bobbateadrink',
};

// ──────────────────────────────────────────────────────────
// State → Face Mapping (enriched with OpenHumans behaviors)
// ──────────────────────────────────────────────────────────

function mapStateToFace(state) {
  switch (state) {
    case 'idle': return 'idle';
    case 'chilling': return 'drinking_boba';
    case 'waiting': return 'reading';
    case 'listening': return 'listening';
    case 'thinking': return 'thinking';
    case 'talking': return 'speaking';
    case 'error': return 'concerned';
    case 'angry': return 'concerned';
    case 'concerned': return 'concerned';
    case 'happy': return 'happy';
    case 'startup': return 'waving';
    case 'praise': return 'proud';
    case 'excited': return 'dancing';
    case 'booting': return 'thinking';
    case 'sleeping': return 'sleep';
    case 'surprised': return 'curious';
    case 'confused': return 'confused';
    case 'writing': return 'writing';
    case 'reading': return 'reading';
    case 'recording': return 'recording';
    case 'drinking_coffee': return 'drinking_coffee';
    case 'cautious': return 'cautious';
    case 'celebrating': return 'celebrating';
    case 'typing': return 'writing';
    default: return 'idle';
  }
}

// ──────────────────────────────────────────────────────────
// Rive View Model Property Resolution
// ──────────────────────────────────────────────────────────

function resolveViewModelProperties(force = false) {
  if (poseProp && visemeProp && !force) return;
  if (!riveInstance) return;

  try {
    // Access the auto-bound ViewModelInstance if available
    let vmInstance = riveInstance.viewModelInstance;
    
    // Fallback to manual resolution if auto-bind is pending
    if (!vmInstance) {
      const defaultVM = typeof riveInstance.defaultViewModel === 'function' ? riveInstance.defaultViewModel() : null;
      if (defaultVM) {
        vmInstance = defaultVM.defaultInstance() || defaultVM.instance();
        if (vmInstance) {
          riveInstance.bindViewModelInstance(vmInstance);
          console.log('[Rive VM] Explicitly bound default ViewModelInstance to artboard.');
        }
      }
    }

    if (vmInstance) {
      poseProp = vmInstance.string('pose') || vmInstance.enum('pose');
      visemeProp = vmInstance.string('mouthVisemeCode') || vmInstance.enum('mouthVisemeCode') || vmInstance.string('viseme') || vmInstance.enum('viseme');
      primaryColorProp = vmInstance.color('primaryColor');
      secondaryColorProp = vmInstance.color('secondaryColor');

      console.log('[Rive VM] poseProp resolved:', !!poseProp);
      console.log('[Rive VM] visemeProp resolved:', !!visemeProp);
      console.log('[Rive VM] primaryColorProp resolved:', !!primaryColorProp);
      console.log('[Rive VM] secondaryColorProp resolved:', !!secondaryColorProp);

      if (poseProp && poseProp.values) {
        console.log('[Rive VM] poseProp valid values:', poseProp.values);
      }
      if (visemeProp && visemeProp.values) {
        console.log('[Rive VM] visemeProp valid values:', visemeProp.values);
      }
    } else {
      console.warn('[Rive VM] No ViewModelInstance found.');
    }
  } catch (err) {
    console.error('[Rive VM] Error resolving View Model properties:', err);
  }
}

// ──────────────────────────────────────────────────────────
// Initialization
// ──────────────────────────────────────────────────────────

export function init3D(containerId, dummyModelPath) {
  container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '';

  canvas = document.createElement('canvas');
  canvas.id = 'mascot-canvas';
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  canvas.width = container.clientWidth || 250;
  canvas.height = container.clientHeight || 250;
  container.appendChild(canvas);

  // Load the .riv file using Node's fs module
  let arrayBuffer = null;
  try {
    const rivPath = path.join(__dirname, 'tiny_mascot.riv');
    console.log('[Rive] Reading mascot file from:', rivPath);
    const rivBuffer = fs.readFileSync(rivPath);
    arrayBuffer = rivBuffer.buffer.slice(rivBuffer.byteOffset, rivBuffer.byteOffset + rivBuffer.byteLength);
  } catch (err) {
    console.error('[Rive] Failed to read tiny_mascot.riv using fs:', err);
  }

  const riveOptions = {
    canvas: canvas,
    autoplay: true,
    autoBind: true,
    stateMachines: ['MascotSM'],
    layout: new rive.Layout({ fit: 'contain', alignment: 'center' }),
    locateFile: (file, path) => {
      if (file.endsWith('.wasm')) {
        return './node_modules/@rive-app/canvas/' + file;
      }
      return path + file;
    },
    onLoad: () => {
      console.log('[Rive] Mascot loaded successfully.');
      console.log('[Rive] State Machine Names:', riveInstance.stateMachineNames);
      console.log('[Rive] Animation Names:', riveInstance.animationNames);
      
      try {
        const stateMachineName = riveInstance.stateMachineNames[0] || 'Main State Machine';
        console.log('[Rive] Activating State Machine:', stateMachineName);
        riveInstance.play(stateMachineName);
        
        try {
          const inputs = riveInstance.stateMachineInputs(stateMachineName);
          if (inputs) {
            console.log('[Rive] State Machine Inputs count:', inputs.length);
            inputs.forEach(input => {
              console.log(`[Rive Input] Name: ${input.name}, Type: ${input.type}`);
            });
          } else {
            console.log('[Rive] No state machine inputs found for:', stateMachineName);
          }
        } catch (e) {
          console.error('[Rive] Error listing state machine inputs:', e);
        }
        
        resolveViewModelProperties(true);
        updateRiveState();
      } catch (err) {
        console.error('[Rive] Error accessing state machine/view model properties:', err);
      }
    },
    onError: (err) => {
      console.error('[Rive] Runtime error:', err);
    }
  };

  if (arrayBuffer) {
    riveOptions.buffer = arrayBuffer;
  } else {
    riveOptions.src = './tiny_mascot.riv';
  }

  riveInstance = new rive.Rive(riveOptions);

  window.addEventListener('resize', onWindowResize);
  requestAnimationFrame(animate);
}

// ──────────────────────────────────────────────────────────
// Window Resize
// ──────────────────────────────────────────────────────────

function onWindowResize() {
  if (canvas && riveInstance) {
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = canvas.parentElement.clientHeight;
    riveInstance.resizeDrawingSurfaceToCanvas();
  }
}

// ──────────────────────────────────────────────────────────
// State Update (with OpenHumans-style transitions)
// ──────────────────────────────────────────────────────────

function updateRiveState() {
  if (!riveInstance) return;

  resolveViewModelProperties();

  // Don't override an ack face that's currently being held
  if (isHoldingAckFace) {
    console.log('[Rive Router] Skipping pose update — ack face is being held');
    return;
  }

  const face = mapStateToFace(currentState);
  const poseName = FACE_TO_POSE[face] || 'idle';

  console.log(`[Rive Router] Updating pose to: ${poseName} (from state: ${currentState})`);

  if (poseProp) {
    try {
      setEnumProperty(poseProp, poseName);
    } catch (e) {
      console.error('[Rive VM Debug] Error setting poseProp:', e);
    }
  }

  // Set colors to match OpenHuman theme
  if (primaryColorProp) {
    try {
      primaryColorProp.value = hexToArgbInt('#F7D145');
    } catch (e) {
      console.error('[Rive VM Debug] Error setting primaryColorProp:', e);
    }
  }
  if (secondaryColorProp) {
    try {
      secondaryColorProp.value = hexToArgbInt('#B23C05');
    } catch (e) {
      console.error('[Rive VM Debug] Error setting secondaryColorProp:', e);
    }
  }

  // Clear speech text on state changes that interrupt speech, and close mouth explicitly
  if (currentState !== 'talking' && visemeProp) {
    visemeQueue = []; 
    try {
      setEnumProperty(visemeProp, 'sil');
      lastVisemeCode = 'sil';
    } catch (e) {
      console.error('[Rive VM Debug] Error resetting visemeProp:', e);
    }
  }
}

// ──────────────────────────────────────────────────────────
// State Setter (enhanced with transition intelligence)
// ──────────────────────────────────────────────────────────

export function set3DState(state) {
  if (currentState === state) return;
  
  previousState = currentState;
  const wasState = currentState;
  currentState = state;
  stateTime = 0;

  console.log(`[Rive Transition] ${wasState} → ${state}`);

  // ── Transition: talking → idle/thinking ──
  // When speech ends, trigger the ack-face analysis instead of snapping to idle
  if (wasState === 'talking' && (state === 'idle' || state === 'thinking')) {
    onSpeechDone();
    // If transitioning to thinking (another round), track it
    if (state === 'thinking') {
      thinkingRoundCount++;
      console.log(`[Rive Transition] Thinking round: ${thinkingRoundCount}`);
    }
    return; // The ack face will handle the transition
  }

  // ── Transition: error → idle ──
  // Show concerned face briefly before going idle
  if (wasState === 'error' && state === 'idle') {
    onErrorOccurred();
    return;
  }
  
  // ── Transition: → thinking (multiple rounds) ──
  // After multiple thinking rounds, switch to drinking_coffee (processing)
  if (state === 'thinking') {
    thinkingRoundCount++;
    if (thinkingRoundCount > 2) {
      console.log(`[Rive Transition] Multiple thinking rounds (${thinkingRoundCount}), switching to drinking_coffee`);
      currentState = 'drinking_coffee';
    }
  }

  // ── Transition: → listening / idle ──
  // Reset round count when user starts a new interaction
  if (state === 'listening' || state === 'idle') {
    thinkingRoundCount = 0;
  }

  // ── Transition: → talking ──
  // Clear ack state so the talking animation plays cleanly
  if (state === 'talking') {
    clearAckTimer();
  }

  // ── Transition: happy / excited / praise ──
  // For positive emotions from Python, use hold-then-idle
  if (state === 'happy' || state === 'praise' || state === 'excited' || state === 'celebrating') {
    clearAckTimer();
    const ackFace = mapStateToFace(state);
    holdThenIdle(ackFace, 1200); // Hold celebration states a bit longer
    return;
  }

  // ── Transition: startup (greeting) ──
  if (state === 'startup') {
    clearAckTimer();
    holdThenIdle('waving', 2000); // Wave for longer on startup
    return;
  }

  updateRiveState();
}

// ──────────────────────────────────────────────────────────
// Animation Loop (with smooth viseme decay)
// ──────────────────────────────────────────────────────────

function animate(timestamp) {
  requestAnimationFrame(animate);

  if (!riveInstance) return;

  resolveViewModelProperties();

  const delta = (timestamp - lastTime) / 1000;
  lastTime = timestamp;
  stateTime += delta;

  // Perform procedural lipsync talk animation
  const isSpeaking = visemeQueue.length > 0;
  if ((isSpeaking || currentState === 'talking') && visemeProp) {
    if (isSpeaking) {
      speechTimer -= delta;
      if (speechTimer <= 0) {
        const frame = visemeQueue.shift();
        if (frame) {
          const code = toRiveVisemeCode(frame.code);
          speechTimer = frame.duration;
          
          try {
            setEnumProperty(visemeProp, code);
            lastVisemeCode = code;
            lastVisemeSetTime = performance.now();
          } catch (e) {
            console.error('[Rive VM Debug] Error setting visemeProp:', e);
          }
        }
      }
    } else {
      // Fallback random visemes if no text but still in talking state
      mouthTimer -= delta;
      if (mouthTimer <= 0) {
        mouthTimer = 0.08 + Math.random() * 0.07;
        try {
          const oculusCode = talkingVisemes[Math.floor(Math.random() * talkingVisemes.length)];
          const code = toRiveVisemeCode(oculusCode);
          setEnumProperty(visemeProp, code);
          lastVisemeCode = code;
          lastVisemeSetTime = performance.now();
        } catch (e) {
          console.error('[Rive VM Debug] Error setting fallback visemeProp:', e);
        }
      }
    }
  } else if (visemeProp) {
    // ── Smooth viseme decay ──
    // Instead of snapping to 'sil', check if we just finished speaking
    // and apply a smooth decay over VISEME_DECAY_MS
    if (lastVisemeCode !== 'sil') {
      const sinceLastViseme = performance.now() - lastVisemeSetTime;
      if (sinceLastViseme >= VISEME_DECAY_MS) {
        // Decay complete — set to silence
        try {
          setEnumProperty(visemeProp, 'sil');
          lastVisemeCode = 'sil';
        } catch (e) {
          console.error('[Rive VM Debug] Error resetting visemeProp:', e);
        }
      }
      // During decay window, keep the last viseme (natural hold before closing)
    }
  }
}
