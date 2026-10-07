// Idle liveliness for the stage: random blinking. Pure (no Babylon imports).
export const BLINK_CLOSE = 0.06;
export const BLINK_OPEN = 0.1;
export const BLINK_MIN_INTERVAL = 2;
export const BLINK_MAX_INTERVAL = 6;

// t: seconds since the blink started. Close linearly, then open linearly.
export function blinkWeight(t) {
  if (t <= 0 || t >= BLINK_CLOSE + BLINK_OPEN) return 0;
  if (t < BLINK_CLOSE) return t / BLINK_CLOSE;
  return 1 - (t - BLINK_CLOSE) / BLINK_OPEN;
}

function nextInterval(random) {
  return BLINK_MIN_INTERVAL + (BLINK_MAX_INTERVAL - BLINK_MIN_INTERVAL) * random();
}

// Intervals are measured start-to-start. setBlink is called every update.
// While paused() (a face that closes the eyes, e.g. happy) the weight stays 0;
// the schedule keeps running so blinking resumes on its next beat.
export function createBlinker({ setBlink, random = Math.random, paused = () => false }) {
  let elapsed = 0;
  let blinkStart = nextInterval(random);

  function update(dt) {
    elapsed += dt;
    while (elapsed - blinkStart >= BLINK_CLOSE + BLINK_OPEN) {
      blinkStart += nextInterval(random);
    }
    setBlink(paused() ? 0 : blinkWeight(elapsed - blinkStart));
  }

  return { update };
}
