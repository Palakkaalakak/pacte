

import { BarType, BarData, PatternType, PatternData } from '../types.ts';

// New coordinate system: -100 to 100. Bars are generated within -90 to 90 to avoid clipping.
const MAX_PRICE = 90;
const MIN_PRICE = -90;
const WORLD_RANGE = MAX_PRICE - MIN_PRICE;

const random = (min: number, max: number): number => Math.random() * (max - min) + min;

/**
 * Generates a Pin Bar based on the new definition.
 * Sentiment is determined by the POSITION of the body, not its color.
 * - Bullish: Body is in the top 1/3 of the bar's range.
 * - Bearish: Body is in the bottom 1/3 of the bar's range.
 */
export const generatePinBar = (options: { isBullish: boolean }): BarData => {
  const { isBullish } = options;
  const range = random(WORLD_RANGE * 0.5, WORLD_RANGE * 0.9);
  const low = random(MIN_PRICE, MAX_PRICE - range);
  const high = low + range;

  const oneThird = range / 3;
  let bodyTop, bodyBottom;

  if (isBullish) { // Bullish Pin: body is in the top 1/3 of the range.
    bodyBottom = high - oneThird;
    bodyTop = high;
  } else { // Bearish Pin: body is in the bottom 1/3 of the range.
    bodyBottom = low;
    bodyTop = low + oneThird;
  }

  // Open and Close are randomly placed within the defined body section.
  // Their relative values can create a red or green body, but the sentiment is already set.
  const open = random(bodyBottom, bodyTop);
  const close = random(bodyBottom, bodyTop);

  return { open, high, low, close, type: BarType.Pin };
};


/**
 * Generates a Mark Up/Down Bar.
 * Sentiment is determined by the COLOR of the body.
 * Body is at least 2/3 of the bar's range.
 */
export const generateMarkBar = (options: { isBullish: boolean }): BarData => {
  const { isBullish } = options;
  const range = random(WORLD_RANGE * 0.7, WORLD_RANGE * 0.95); // Needs a large body
  const low = random(MIN_PRICE, MAX_PRICE - range);
  const high = low + range;
  const bodySize = range * random(2/3, 0.9); // Body is at least 2/3 of range
  
  let open, close;

  if (isBullish) { // Green bar
    open = random(low, high - bodySize);
    close = open + bodySize;
  } else { // Red bar
    open = random(low + bodySize, high);
    close = open - bodySize;
  }

  return { open, high, low, close, type: BarType.Mark };
};

/**
 * Generates an Ice Cream Bar based on the new definition.
 * Sentiment is determined by the POSITION of the close, not body color.
 * - Body is ~1/2 the total range.
 * - Bullish: Close is in the top 1/3 of the range.
 * - Bearish: Close is in the bottom 1/3 of the range.
 */
export const generateIceCreamBar = (options: { isBullish: boolean }): BarData => {
  const { isBullish } = options;
  const range = random(WORLD_RANGE * 0.5, WORLD_RANGE * 0.9);
  const low = random(MIN_PRICE, MAX_PRICE - range);
  const high = low + range;

  const bodySize = range / 2;
  let close: number;
  
  if (isBullish) {
    const topThirdStart = high - range / 3;
    close = random(topThirdStart, high);
  } else {
    const bottomThirdEnd = low + range / 3;
    close = random(low, bottomThirdEnd);
  }

  // Randomly decide if the bar is green or red, the sentiment is already determined by the close position.
  const open = Math.random() > 0.5 ? close - bodySize : close + bodySize;

  return { open, high, low, close, type: BarType.IceCream };
};


/**
 * Generates a bar that does not meet any of the EXE criteria.
 */
export const generateOtherBar = (): BarData => {
  const range = random(WORLD_RANGE * 0.3, WORLD_RANGE * 0.6);
  const low = random(MIN_PRICE, MAX_PRICE - range);
  const high = low + range;

  // Body is small and in the middle of the range, typical of a spinning top.
  const middleThirdStart = low + range / 3;
  const middleThirdEnd = high - range / 3;
  
  const bodySize = random(range * 0.05, range * 0.25); // Small body
  const open = random(middleThirdStart, middleThirdEnd - bodySize);
  const close = open + bodySize;


  return { open, high, low, close, type: BarType.Other };
};

export const generateExeBar = (options: { isBullish: boolean }): BarData => {
  const exeBarGenerators = [
    () => generatePinBar(options), 
    () => generateMarkBar(options), 
    () => generateIceCreamBar(options)
  ];
  const randomIndex = Math.floor(Math.random() * exeBarGenerators.length);
  return exeBarGenerators[randomIndex]();
};

export const generateRandomBar = (): BarData => {
    const isExe = Math.random() > 0.5;
    if (isExe) {
        return generateExeBar({ isBullish: Math.random() > 0.5 });
    } else {
        return generateOtherBar();
    }
};


// --- PATTERN GENERATION ---

const generateMotherBar = (): BarData => {
    const range = random(80, 120);
    const low = random(MIN_PRICE + 40, MAX_PRICE - range - 40);
    const high = low + range;
    const open = random(low, high);
    const close = random(low, high);
    return {open, high, low, close, type: BarType.Other};
}

const generateInsideBar = (mother: BarData): BarData => {
    const motherRange = mother.high - mother.low;
    const range = random(motherRange * 0.2, motherRange * 0.7);
    const high = random(mother.low + range, mother.high);
    const low = high - range;
    const open = random(low, high);
    const close = random(low, high);
    return {open, high, low, close, type: BarType.Other};
}

const generateForceStrikeReversalCluster = (motherBar: BarData, isBullish: boolean, options?: { lpLevel?: number; isSlow?: boolean; noExe?: boolean; }): BarData[] => {
    const { lpLevel, isSlow = false, noExe = false } = options || {};
    const reversalBars: BarData[] = [];
    // Rule: max 3 bars for valid cluster. Generate 4-5 for the "slow" flaw.
    const numBarsInCluster = isSlow ? Math.floor(random(4, 6)) : Math.floor(random(1, 4));
    const breakoutLevel = lpLevel !== undefined ? lpLevel : (isBullish ? motherBar.low : motherBar.high);
    
    // Start price for the cluster is based on a point within the mother bar's body.
    const motherBodyTop = Math.max(motherBar.open, motherBar.close);
    const motherBodyBottom = Math.min(motherBar.open, motherBar.close);
    let currentPrice = random(motherBodyBottom, motherBodyTop);
    
    // Generate the bars that move towards the breakout (n-1 bars)
    for (let i = 0; i < numBarsInCluster - 1; i++) {
        const open = currentPrice;
        const move = isBullish ? random(-15, -5) : random(5, 15);
        const close =