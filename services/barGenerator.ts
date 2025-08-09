

import { BarType, BarData, PatternType, PatternData, LpLine } from '../types.ts';

// New coordinate system: -100 to 100.
const Y_MAX = 100;
const Y_MIN = -100;
// Bars are generated within a slightly smaller "safe" area to provide a margin.
const SAFE_MAX = 90;
const SAFE_MIN = -90;
const WORLD_RANGE = SAFE_MAX - SAFE_MIN;

const random = (min: number, max: number): number => Math.random() * (max - min) + min;

/**
 * Checks if a pattern's bars are all within the visible Y-axis range.
 */
const isPatternInBounds = (pattern: BarData[]): boolean => {
    for (const bar of pattern) {
        if (bar.high > Y_MAX || bar.low < Y_MIN) {
            return false; // Out of bounds
        }
    }
    return true; // In bounds
};

/**
 * Generates a Pin Bar based on the new definition.
 * Sentiment is determined by the POSITION of the body, not its color.
 * - Bullish: Body is in the top 1/3 of the bar's range.
 * - Bearish: Body is in the bottom 1/3 of the bar's range.
 */
export const generatePinBar = (options: { isBullish: boolean }): BarData => {
  const { isBullish } = options;
  const range = random(WORLD_RANGE * 0.6, WORLD_RANGE * 0.9);
  const low = random(SAFE_MIN, SAFE_MAX - range);
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
  const low = random(SAFE_MIN, SAFE_MAX - range);
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
  const range = random(WORLD_RANGE * 0.6, WORLD_RANGE * 0.9);
  const low = random(SAFE_MIN, SAFE_MAX - range);
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
  const low = random(SAFE_MIN, SAFE_MAX - range);
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
    const low = random(SAFE_MIN + 40, SAFE_MAX - range - 40);
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
        const move = isBullish ? random(-25, -10) : random(10, 25);
        const close = open + move;
        const high = Math.max(open, close) + random(2, 8);
        const low = Math.min(open, close) - random(2, 8);
        reversalBars.push({ open, high, low, close, type: BarType.Other });
        currentPrice = close;
    }

    // The final Reversal Bar
    const open = currentPrice;
    let reversalExeBar: BarData;
    
    if (noExe) {
        // Generate a non-exe bar that still respects the reversal logic
        const close = isBullish 
            ? random(breakoutLevel + 5, breakoutLevel + 20) // Reverse bullishly
            : random(breakoutLevel - 20, breakoutLevel - 5); // Reverse bearishly
        const high = Math.max(open, close) + random(2, 8);
        const low = Math.min(open, close) - random(2, 8);
        reversalExeBar = { open, high, low, close, type: BarType.Other };
    } else {
        // Use an actual EXE bar generator for the reversal
        reversalExeBar = generateExeBar({ isBullish });
        // Adjust its position to logically follow the previous bar
        const range = reversalExeBar.high - reversalExeBar.low;
        const newLow = isBullish ? open - range * random(0.6, 0.9) : open - range * random(0.1, 0.4);
        const newHigh = newLow + range;
        reversalExeBar.low = newLow;
        reversalExeBar.high = newHigh;
        reversalExeBar.open = open;
        // Ensure the close is in the right place relative to the breakout level
        if (isBullish) {
            reversalExeBar.close = random(breakoutLevel + 5, newHigh - (newHigh-newLow)*0.1);
        } else {
            reversalExeBar.close = random(newLow + (newHigh-newLow)*0.1, breakoutLevel - 5);
        }
    }
    reversalBars.push(reversalExeBar);

    return reversalBars;
};

const _generateRandomPattern = (): PatternData => {
  const isBullish = Math.random() > 0.5;
  const isFlawed = Math.random() > 0.4; // 40% chance of a flawed pattern

  const motherBar = generateMotherBar();
  const insideBar = generateInsideBar(motherBar);
  const pattern = [motherBar, insideBar];

  const lpLevel = isBullish ? motherBar.low : motherBar.high;
  const lpLines: LpLine[] = [{ level: lpLevel, sourceIndex: 0 }];

  if (isFlawed) {
    // flaw: break out but don't reverse back in
    const breakoutBar = generateExeBar({ isBullish: !isBullish });
    const range = breakoutBar.high - breakoutBar.low;
    const breakoutStart = random(insideBar.low, insideBar.high);
    
    if (isBullish) { // Bullish FS should break low first
        const newLow = motherBar.low - range * random(0.1, 0.4);
        breakoutBar.low = newLow;
        breakoutBar.high = newLow + range;
        breakoutBar.open = breakoutStart;
        breakoutBar.close = newLow + random(1, range * 0.2); // fails to reverse
    } else { // Bearish FS should break high first
        const newHigh = motherBar.high + range * random(0.1, 0.4);
        breakoutBar.high = newHigh;
        breakoutBar.low = newHigh - range;
        breakoutBar.open = breakoutStart;
        breakoutBar.close = newHigh - random(1, range * 0.2); // fails to reverse
    }
    pattern.push(breakoutBar);
    return { pattern, type: PatternType.Other, lpLines };
  }

  // Valid FS
  const reversalCluster = generateForceStrikeReversalCluster(motherBar, isBullish);
  pattern.push(...reversalCluster);
  
  return {
    pattern,
    type: isBullish ? PatternType.BullishFS : PatternType.BearishFS,
    lpLines
  };
};

export const generateRandomPattern = (): PatternData => {
  let data: PatternData;
  let attempts = 0;
  const maxAttempts = 30; // Prevent infinite loop
  do {
    data = _generateRandomPattern();
    attempts++;
  } while (!isPatternInBounds(data.pattern) && attempts < maxAttempts);
  return data;
};

export const generateRandomTrendPattern = (): PatternData => {
    // Simplified version for now, doesn't use SMAs yet
    return generateRandomPattern();
}

const _generateFSAtSwingPointPattern = (): PatternData => {
    const isBullish = Math.random() > 0.5;
    const historyBars: BarData[] = [];
    
    let currentPrice = random(-10, 10);
    const trendDirection = isBullish ? -1 : 1; // Trend leading to the swing point
    
    // Generate trend leading to the swing point (reduced bar count)
    for(let i=0; i < 2; i++) {
        const open = currentPrice;
        const close = open + trendDirection * random(25, 40);
        const high = Math.max(open, close) + random(2, 5);
        const low = Math.min(open, close) - random(2, 5);
        historyBars.push({ open, high, low, close, type: BarType.Other });
        currentPrice = close;
    }
    
    // The swing point bar
    const swingBarOpen = currentPrice;
    const swingBarClose = swingBarOpen + trendDirection * random(5, 10);
    const swingHigh = isBullish ? Math.max(swingBarOpen, swingBarClose) + random (1, 3) : Math.max(swingBarOpen, swingBarClose) + random(15, 25);
    const swingLow = isBullish ? Math.min(swingBarOpen, swingBarClose) - random(15, 25) : Math.min(swingBarOpen, swingBarClose) - random(1, 3);
    const swingBar = { open: swingBarOpen, high: swingHigh, low: swingLow, close: swingBarClose, type: BarType.Other };
    historyBars.push(swingBar);
    
    const lpLevel = isBullish ? swingLow : swingHigh;
    const lpSourceIndex = historyBars.length - 1;
    const lpLines: LpLine[] = [{ level: lpLevel, sourceIndex: lpSourceIndex }];

    // Retracement away from swing point (reduced bar count)
    for(let i=0; i < 1; i++) {
        const open = currentPrice;
        const close = open - trendDirection * random(18, 28);
        const high = Math.max(open, close) + random(2, 5);
        const low = Math.min(open, close) - random(2, 5);
        historyBars.push({ open, high, low, close, type: BarType.Other });
        currentPrice = close;
    }

    // Return to test the swing point
    const testBarOpen = currentPrice;
    const testBarClose = lpLevel + trendDirection * random(-5, 5); // Close near the level
    const testHigh = Math.max(testBarOpen, testBarClose) + random(2, 5);
    const testLow = Math.min(testBarOpen, testBarClose) - random(2, 5);
    const testBar = { open: testBarOpen, high: testHigh, low: testLow, close: testBarClose, type: BarType.Other };

    const motherBar = testBar; // The bar that tests the level acts as the mother bar
    const insideBar = generateInsideBar(motherBar);
    
    const finalPattern = [...historyBars, motherBar, insideBar];
    const isFlawed = Math.random() > 0.5;

    if (isFlawed) {
        const cluster = generateForceStrikeReversalCluster(motherBar, isBullish, { lpLevel, noExe: true });
        finalPattern.push(...cluster);
        return { pattern: finalPattern, type: PatternType.Other, lpLines };
    }

    const reversalCluster = generateForceStrikeReversalCluster(motherBar, isBullish, { lpLevel });
    finalPattern.push(...reversalCluster);

    return {
        pattern: finalPattern,
        type: isBullish ? PatternType.BullishFS : PatternType.BearishFS,
        lpLines
    };
}

export const generateFSAtSwingPointPattern = (): PatternData => {
    let data: PatternData;
    let attempts = 0;
    const maxAttempts = 30; // Prevent infinite loop
    do {
        data = _generateFSAtSwingPointPattern();
        attempts++;
    } while (!isPatternInBounds(data.pattern) && attempts < maxAttempts);
    return data;
}

const _generateRandomReversal1Pattern = (): PatternData => {
    const isBullish = Math.random() > 0.5; // True for DR1 (bullish), false for UR1 (bearish)
    const isFlawed = Math.random() > 0.4;
    const pattern: BarData[] = [];
    
    let currentPrice = random(-20, 20);
    const trendDirection = isBullish ? -1 : 1;

    // 1. Establish initial trend leading to Point X (more volatile)
    for (let i = 0; i < 2; i++) {
        const open = currentPrice;
        const close = open + trendDirection * random(30, 50);
        const high = Math.max(open, close) + random(5, 10);
        const low = Math.min(open, close) - random(5, 10);
        pattern.push({ open, high, low, close, type: BarType.Other });
        currentPrice = close;
    }

    // 2. The Point X bar (swing low for DR1, swing high for UR1) (more volatile)
    const pointXBar = {
        open: currentPrice,
        high: currentPrice + random(5, 10),
        low: currentPrice - random(5, 10),
        close: currentPrice + trendDirection * random(1, 5),
        type: BarType.Other
    };
    if (isBullish) pointXBar.low = currentPrice - random(30, 50);
    else pointXBar.high = currentPrice + random(30, 50);
    pattern.push(pointXBar);
    currentPrice = pointXBar.close;
    const lpLevel = isBullish ? pointXBar.low : pointXBar.high;
    const lpSourceIndex = pattern.length - 1;

    // 3. Retrace to establish Point Y (more volatile)
    for (let i = 0; i < 1; i++) {
        const open = currentPrice;
        const close = open - trendDirection * random(35, 60);
        const high = Math.max(open, close) + random(5, 10);
        const low = Math.min(open, close) - random(5, 10);
        pattern.push({ open, high, low, close, type: BarType.Other });
        currentPrice = close;
    }
    const pointYBar = pattern[pattern.length -1];
    const secondaryLpLevel = isBullish ? pointYBar.high : pointYBar.low;
    const secondaryLpSourceIndex = pattern.length - 1;
    
    const lpLines: LpLine[] = [
        { level: lpLevel, sourceIndex: lpSourceIndex },
        { level: secondaryLpLevel, sourceIndex: secondaryLpSourceIndex }
    ];

    // 4. Flush move back to test Point X (1-3 bars)
    const numFlushBars = isFlawed ? 5 : Math.floor(random(1, 4));
    for (let i = 0; i < numFlushBars; i++) {
        const open = currentPrice;
        const target = lpLevel + trendDirection * random(1, 10);
        const close = open + (target - open) / (numFlushBars - i);
        const high = Math.max(open, close) + random(2, 5);
        const low = Math.min(open, close) - random(2, 5);
        pattern.push({ open, high, low, close, type: BarType.Other });
        currentPrice = close;
    }

    // 5. The final EXE bar
    const exeBar = generateExeBar({ isBullish });
    // Adjust its position
    const range = exeBar.high - exeBar.low;
    const newLow = isBullish ? currentPrice - range * random(0.1, 0.4) : currentPrice - range * random(0.6, 0.9);
    exeBar.low = newLow;
    exeBar.high = newLow + range;
    exeBar.open = currentPrice;
    
    if (isBullish) { // DR1 should close AT or ABOVE lpLevel (Point X low)
        exeBar.close = random(lpLevel, lpLevel + 20);
    } else { // UR1 should close AT or BELOW lpLevel (Point X high)
        exeBar.close = random(lpLevel - 20, lpLevel);
    }

    if (isFlawed) {
        // flaw: final bar is not an EXE
        const flawedBar = generateOtherBar();
        flawedBar.open = exeBar.open;
        flawedBar.close = exeBar.close;
        flawedBar.low = Math.min(flawedBar.open, flawedBar.close) - random(5,10);
        flawedBar.high = Math.max(flawedBar.open, flawedBar.close) + random(5,10);
        pattern.push(flawedBar);
    } else {
        pattern.push(exeBar);
    }

    const type = isFlawed ? PatternType.Other : (isBullish ? PatternType.DownsideReversal1 : PatternType.UpsideReversal1);

    return { pattern, type, lpLines };
}

export const generateRandomReversal1Pattern = (): PatternData => {
    let data: PatternData;
    let attempts = 0;
    const maxAttempts = 30; // Prevent infinite loop
    do {
        data = _generateRandomReversal1Pattern();
        attempts++;
    } while (!isPatternInBounds(data.pattern) && attempts < maxAttempts);
    return data;
}

// --- NEW CONTINUATION 1 (UC1/DC1) PATTERNS ---

const calculateSMA = (data: number[], period: number): (number | undefined)[] => {
    if (period <= 0) return new Array(data.length).fill(undefined);
    const sma: (number | undefined)[] = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            sma.push(undefined);
        } else {
            const slice = data.slice(i - period + 1, i + 1);
            const sum = slice.reduce((a, b) => a + b, 0);
            sma.push(sum / period);
        }
    }
    return sma;
};

const generateContinuation1Pattern = (isBullish: boolean, isFlawed: boolean = false): PatternData => {
    const precursorBars: BarData[] = [];
    const trendDirection = isBullish ? 1 : -1;
    let currentPrice = random(-80, -60) * trendDirection;

    // 0. Generate 50 precursor bars for accurate SMA calculation
    for (let i = 0; i < 50; i++) {
        const open = currentPrice;
        const move = trendDirection * random(1, 3) + (Math.random() - 0.5) * 2;
        currentPrice = open + move;
        const high = Math.max(open, currentPrice) + random(1, 3);
        const low = Math.min(open, currentPrice) - random(1, 3);
        precursorBars.push({ open, high, low, close: currentPrice, type: BarType.Other });
    }
    
    const visiblePattern: BarData[] = [];
    const lpLines: LpLine[] = [];

    // 1. Initial push to create Point A (fewer bars, more volatile)
    const pointARunBars = 2;
    for (let i = 0; i < pointARunBars; i++) {
        const open = currentPrice;
        const move = trendDirection * random(15, 30);
        currentPrice = open + move;
        const high = Math.max(open, currentPrice) + random(2, 5);
        const low = Math.min(open, currentPrice) - random(2, 5);
        visiblePattern.push({ open, high, low, close: currentPrice, type: BarType.Other });
    }
    const pointABar = isBullish ? visiblePattern.reduce((prev, curr) => prev.high > curr.high ? prev : curr) : visiblePattern.reduce((prev, curr) => prev.low < curr.low ? prev : curr);
    lpLines.push({ level: isBullish ? pointABar.high : pointABar.low, sourceIndex: visiblePattern.indexOf(pointABar) });

    // 2. Pullback towards SMAs (Point B) (fewer bars, more volatile)
    const pointBRunBars = 2;
    for (let i = 0; i < pointBRunBars; i++) {
        const open = currentPrice;
        const move = -trendDirection * random(20, 35);
        currentPrice = open + move;
        const high = Math.max(open, currentPrice) + random(2, 4);
        const low = Math.min(open, currentPrice) - random(2, 4);
        visiblePattern.push({ open, high, low, close: currentPrice, type: BarType.Other });
    }
    const pointBStartIndex = pointARunBars;
    const pointBcandidateBars = visiblePattern.slice(pointBStartIndex);
    const pointBBar = isBullish ? pointBcandidateBars.reduce((prev, curr) => prev.low < curr.low ? prev : curr) : pointBcandidateBars.reduce((prev, curr) => prev.high > curr.high ? prev : curr);
    lpLines.push({ level: isBullish ? pointBBar.low : pointBBar.high, sourceIndex: visiblePattern.indexOf(pointBBar) });


    // 3. Rally to a lower high / higher low (Point C) (fewer bars, more volatile)
    const pointCRunBars = 1;
    for (let i = 0; i < pointCRunBars; i++) {
        const open = currentPrice;
        const move = trendDirection * random(10, 25);
        currentPrice = open + move;
        const high = Math.max(open, currentPrice) + random(2, 4);
        const low = Math.min(open, currentPrice) - random(2, 4);
        visiblePattern.push({ open, high, low, close: currentPrice, type: BarType.Other });
    }
    const pointCStartIndex = pointBStartIndex + pointBRunBars;
    const pointCcandidateBars = visiblePattern.slice(pointCStartIndex);
    const pointCBar = isBullish ? pointCcandidateBars.reduce((prev, curr) => prev.high > curr.high ? prev : curr) : pointCcandidateBars.reduce((prev, curr) => prev.low < curr.low ? prev : curr);
    lpLines.push({ level: isBullish ? pointCBar.high : pointCBar.low, sourceIndex: visiblePattern.indexOf(pointCBar) });
    const breakoutLevel = lpLines[2].level;

    // 4. Dip before breakout (Point D)
    for (let i = 0; i < 1; i++) {
        const open = currentPrice;
        const move = -trendDirection * random(6, 12);
        currentPrice = open + move;
        const high = Math.max(open, currentPrice) + random(2, 5);
        const low = Math.min(open, currentPrice) - random(2, 5);
        visiblePattern.push({ open, high, low, close: currentPrice, type: BarType.Other });
    }
    
    // 5. Generate recovery and breakout attempt
    const takesTooLong = isFlawed && Math.random() < 0.33;
    const numRecoveryBars = takesTooLong ? Math.floor(random(6, 8)) : Math.floor(random(1, 3));
    
    for (let i = 0; i < numRecoveryBars - 1; i++) {
        const open = currentPrice;
        const move = trendDirection * random(10, 20);
        currentPrice = open + move;
        const high = Math.max(open, currentPrice) + random(2, 5);
        const low = Math.min(open, currentPrice) - random(2, 5);
        visiblePattern.push({ open, high, low, close: currentPrice, type: BarType.Other });
    }

    // 6. The final EXE bar
    const notExeBar = isFlawed && Math.random() < 0.5;
    let finalBar: BarData = notExeBar ? generateOtherBar() : generateExeBar({ isBullish });
    
    finalBar.open = currentPrice;
    const range = finalBar.high - finalBar.low;
    const failsBreakout = isFlawed && !takesTooLong && !notExeBar;

    if(isBullish) {
        finalBar.low = currentPrice - range * random(0.1, 0.4);
        finalBar.high = finalBar.low + range;
        const closeTarget = breakoutLevel + (failsBreakout ? random(-15, -1) : random(5, 20));
        finalBar.close = Math.min(closeTarget, finalBar.high - 2);
    } else {
        finalBar.high = currentPrice + range * random(0.1, 0.4);
        finalBar.low = finalBar.high - range;
        const closeTarget = breakoutLevel + (failsBreakout ? random(1, 15) : random(-20, -5));
        finalBar.close = Math.max(closeTarget, finalBar.low + 2);
    }
    visiblePattern.push(finalBar);

    // Calculate SMAs on combined history and visible pattern
    const allClosePrices = [...precursorBars.map(b => b.close), ...visiblePattern.map(b => b.close)];
    const fullSma20 = calculateSMA(allClosePrices, 20);
    const fullSma50 = calculateSMA(allClosePrices, 50);

    // Slice SMA arrays to match the visible pattern's length
    const sma20 = fullSma20.slice(precursorBars.length);
    const sma50 = fullSma50.slice(precursorBars.length);

    // Flaw: incorrect trend based on SMAs at the end
    const lastSma20 = sma20[sma20.length - 1];
    const lastSma50 = sma50[sma50.length - 1];
    let isTrendFlawed = false;
    if (lastSma20 !== undefined && lastSma50 !== undefined) {
        if (isBullish && lastSma20 < lastSma50) isTrendFlawed = true;
        if (!isBullish && lastSma20 > lastSma50) isTrendFlawed = true;
    }

    const patternIsTrulyFlawed = takesTooLong || notExeBar || failsBreakout || (isFlawed && isTrendFlawed);
    const type = patternIsTrulyFlawed ? PatternType.Other : (isBullish ? PatternType.UpsideContinuation1 : PatternType.DownsideContinuation1);

    return { pattern: visiblePattern, type, lpLines, sma20, sma50 };
};


export const generateRandomContinuation1Pattern = (): PatternData => {
    let data: PatternData;
    let attempts = 0;
    const maxAttempts = 30; // Prevent infinite loop
    do {
        const isBullish = Math.random() > 0.5;
        const isFlawed = Math.random() > 0.4;
        data = generateContinuation1Pattern(isBullish, isFlawed);
        attempts++;
    } while (!isPatternInBounds(data.pattern) && attempts < maxAttempts);

    return data;
};
