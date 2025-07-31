
export enum SoundType {
  Correct,
  Incorrect,
  Timeout,
}

// Global AudioContext. Initialize it lazily on first use.
let audioContext: AudioContext | null = null;

const initializeAudioContext = () => {
  if (typeof window !== 'undefined' && !audioContext) {
    // Create AudioContext after a user gesture, which is a requirement in modern browsers.
    audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
  }
};

/**
 * Plays a sound effect based on the given type.
 * This must be called after a user interaction (e.g., a click) to work in modern browsers.
 * @param type The type of sound to play.
 */
export const playSound = (type: SoundType) => {
  initializeAudioContext();
  if (!audioContext) {
    console.warn("AudioContext could not be initialized. Sounds will be disabled.");
    return;
  }

  // To prevent issues with autoplay policies, resume the context if it's suspended.
  if (audioContext.state === 'suspended') {
    audioContext.resume();
  }

  const now = audioContext.currentTime;
  let oscillator: OscillatorNode;
  let gainNode: GainNode;

  gainNode = audioContext.createGain();
  gainNode.connect(audioContext.destination);

  switch (type) {
    case SoundType.Correct: {
      // A pleasant, rising two-tone effect
      // First tone (C5)
      const osc1 = audioContext.createOscillator();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(523.25, now); // C5
      osc1.connect(gainNode);
      osc1.start(now);
      osc1.stop(now + 0.1);

      // Second tone (G5)
      const osc2 = audioContext.createOscillator();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(783.99, now + 0.1); // G5
      osc2.connect(gainNode);
      osc2.start(now + 0.1);
      osc2.stop(now + 0.25);
      
      gainNode.gain.setValueAtTime(0.3, now);
      gainNode.gain.exponentialRampToValueAtTime(0.0001, now + 0.25);
      break;
    }
    case SoundType.Incorrect: {
      // A short, low, dissonant buzz
      oscillator = audioContext.createOscillator();
      oscillator.type = 'sawtooth';
      oscillator.frequency.setValueAtTime(160, now);
      oscillator.frequency.exponentialRampToValueAtTime(100, now + 0.2);
      
      gainNode.gain.setValueAtTime(0.25, now);
      gainNode.gain.exponentialRampToValueAtTime(0.0001, now + 0.2);
      
      oscillator.connect(gainNode);
      oscillator.start(now);
      oscillator.stop(now + 0.2);
      break;
    }
    case SoundType.Timeout: {
      // A low, steady buzz
      oscillator = audioContext.createOscillator();
      oscillator.type = 'square';
      oscillator.frequency.setValueAtTime(120, now);
      
      gainNode.gain.setValueAtTime(0.2, now);
      gainNode.gain.exponentialRampToValueAtTime(0.0001, now + 0.4);
      
      oscillator.connect(gainNode);
      oscillator.start(now);
      oscillator.stop(now + 0.4);
      break;
    }
  }
};
