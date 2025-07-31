import React from 'react';
import type { BarData, PatternData } from '../types.ts';
import { BarType, PatternType } from '../types.ts';
import Candlestick from './Candlestick.tsx';
import CandlestickPattern from './CandlestickPattern.tsx';
import ChartWithAxis from './ChartWithAxis.tsx';

interface InfoModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const exampleBars: Record<string, BarData> = {
    [BarType.Pin]: { high: 80, low: -80, open: 65, close: 75, type: BarType.Pin },
    [BarType.Mark]: { high: 80, low: -40, open: -30, close: 50, type: BarType.Mark },
    [BarType.IceCream]: { high: 80, low: -70, open: -5, close: 70, type: BarType.IceCream },
};

const examplePatterns: Record<string, PatternData> = {
    [PatternType.BullishFS]: {
        "pattern": [
            { "open": 40.5, "high": 80, "low": -39.5, "close": 2, "type": BarType.Other },
            { "open": -1, "high": 37, "low": -19, "close": 11, "type": BarType.Other },
            { "open": -49, "high": 17, "low": -60, "close": -15, "type": BarType.Pin }
        ],
        "type": PatternType.BullishFS,
        "lpLevel": -39.5
    },
    [PatternType.BearishFS]: {
        "pattern": [
            { "open": 2, "high": 42, "low": -78, "close": 30, "type": BarType.Other },
            { "open": 20, "high": 32, "low": -26, "close": -15, "type": BarType.Other },
            { "open": 50, "high": 60, "low": 15, "close": 25, "type": BarType.Pin }
        ],
        "type": PatternType.BearishFS,
        "lpLevel": 42
    },
    'BullishFSAtSwingPoint': {
        "pattern": [
            { "open": -2.7, "high": 2.3, "low": -27.7, "close": -22.7, "type": BarType.Other },
            { "open": -22.7, "high": -17.7, "low": -47.7, "close": -42.7, "type": BarType.Other },
            { "open": -42.7, "high": -32.7, "low": -82.7, "close": -77.7, "type": BarType.Other },
            { "open": -77.7, "high": -57.7, "low": -72.7, "close": -62.7, "type": BarType.Other },
            { "open": -62.7, "high": -42.7, "low": -57.7, "close": -47.7, "type": BarType.Other },
            { "open": -54.9, "high": -14.9, "low": -59.9, "close": -24.9, "type": BarType.Other },
            { "open": -24.9, "high": 0.1, "low": -42.9, "close": -27.9, "type": BarType.Other },
            { "open": -92.7, "high": -52.7, "low": -103.7, "close": -77.7, "type": BarType.Pin }
        ],
        "type": PatternType.BullishFS,
        "lpLevel": -82.7,
        "lpSourceIndex": 2
    },
    [PatternType.UpsideReversal1]: {
        "pattern": [
            {"open":-17,"high":27,"low":-20,"close":24,"type":BarType.Other},
            {"open":24,"high":41,"low":18,"close":39,"type":BarType.Other},
            {"open":39,"high":-5,"low":-28,"close":-8,"type":BarType.Other},
            {"open":-8,"high":-24,"low":-44,"close":-42,"type":BarType.Other},
            {"open":-42,"high":-30,"low":-47,"close":-32,"type":BarType.Other},
            {"open":-32,"high":42,"low":-43,"close":36,"type":BarType.Other},
            {"open":36,"high":37,"low":26,"close":31,"type":BarType.Other},
            {"open":50,"high":52,"low":23,"close":25,"type":BarType.Mark}
        ],
        "type": PatternType.UpsideReversal1,
        "lpLevel": 41,
        "lpSourceIndex": 1,
        "secondaryLpLevel": -44,
        "secondaryLpSourceIndex": 3
    },
    [PatternType.DownsideReversal1]: {
       "pattern":[
           {"open":31,"high":34,"low":-11,"close":-8,"type":BarType.Other},
           {"open":-8,"high":-1,"low":-28,"close":-25,"type":BarType.Other},
           {"open":-25,"high":35,"low":-28,"close":31,"type":BarType.Other},
           {"open":31,"high":41,"low":25,"close":39,"type":BarType.Other},
           {"open":39,"high":44,"low":28,"close":36,"type":BarType.Other},
           {"open":36,"high":40,"low":-34,"close":-28,"type":BarType.Other},
           {"open":-28,"high":-18,"low":-29,"close":-22,"type":BarType.Other},
           {"open":-40,"high":-13,"low":-43,"close":-18,"type":BarType.Mark}
        ],
        "type":PatternType.DownsideReversal1,
        "lpLevel":-28,
        "lpSourceIndex":1,
        "secondaryLpLevel":41,
        "secondaryLpSourceIndex":3
    }
}

const InfoSection: React.FC<{ title: string; children: React.ReactNode; visual?: React.ReactNode; }> = ({ title, children, visual }) => (
    <div className="flex flex-col md:flex-row items-center md:items-start gap-6">
        {visual && (
            <div className="w-full md:w-48 h-40 flex-shrink-0 bg-slate-800/50 rounded-lg p-1">
                <ChartWithAxis>
                  {visual}
                </ChartWithAxis>
            </div>
        )}
        <div className="text-left flex-1">
            <h4 className="text-xl font-bold text-cyan-400 mb-2">{title}</h4>
            <div className="space-y-2 text-slate-300">{children}</div>
        </div>
    </div>
);

const InfoModal: React.FC<InfoModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div 
        className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
        onClick={onClose}
        role="dialog"
        aria-modal="true"
        aria-labelledby="info-modal-title"
    >
        <div 
            className="bg-slate-900 border border-slate-700 rounded-2xl p-6 md:p-8 max-w-4xl w-full max-h-[90vh] overflow-y-auto"
            onClick={e => e.stopPropagation()}
        >
            <div className="flex justify-between items-center mb-6 sticky top-0 bg-slate-900 -mt-6 -mx-8 pt-6 px-8 pb-4 z-10">
                <h2 id="info-modal-title" className="text-3xl font-bold text-white">Pattern & Strategy Guide</h2>
                <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close guide">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
            </div>
            
            <div className="space-y-10">
                <section>
                    <h3 className="text-2xl font-bold text-indigo-400 border-b border-indigo-400/30 pb-2 mb-6">EXE Bar Types</h3>
                    <div className="space-y-8">
                        <InfoSection title="Pin Bar" visual={<div className="w-24 h-full mx-auto"><Candlestick bar={exampleBars[BarType.Pin]} /></div>}>
                            <p>Shows price rejection. The long wick (or "tail") indicates that price moved significantly in one direction but was pushed back by opposing pressure.</p>
                            <ul className="list-disc list-inside">
                                <li><strong>Key Feature:</strong> Body is in the top 1/3 (bullish) or bottom 1/3 (bearish) of the bar's total range.</li>
                            </ul>
                        </InfoSection>
                        <InfoSection title="Mark Up/Down Bar" visual={<div className="w-24 h-full mx-auto"><Candlestick bar={exampleBars[BarType.Mark]} /></div>}>
                           <p>Indicates strong, sustained momentum. The bar closes strongly in the direction of the trend with very little fight from the other side.</p>
                           <ul className="list-disc list-inside">
                               <li><strong>Key Feature:</strong> The body covers at least 2/3 of the bar's total range.</li>
                           </ul>
                        </InfoSection>
                        <InfoSection title="Ice Cream Bar" visual={<div className="w-24 h-full mx-auto"><Candlestick bar={exampleBars[BarType.IceCream]} /></div>}>
                           <p>Represents a "scoop" of momentum. It shows a significant price push but with a close that isn't at the extreme high/low.</p>
                           <ul className="list-disc list-inside">
                               <li><strong>Key Feature:</strong> Body is ~1/2 of the range, and the close is in the top 1/3 (bullish) or bottom 1/3 (bearish) of the range.</li>
                           </ul>
                        </InfoSection>
                    </div>
                </section>

                <div className="border-t border-slate-700/50"></div>
                
                <section>
                    <h3 className="text-2xl font-bold text-indigo-400 border-b border-indigo-400/30 pb-2 mb-6">The Force Strike (FS) Pattern</h3>
                     <p className="text-slate-300 mb-6">The Force Strike is a core price action pattern that reveals a potential "trap" set by market makers. It consists of three key components: a Mother Bar, one or more Inside Bars, and a Reversal Bar.</p>
                    <div className="space-y-8">
                        <InfoSection title="Bullish Force Strike" visual={<CandlestickPattern {...examplePatterns[PatternType.BullishFS]} showLevels={true} />} >
                           <p>A bullish reversal pattern that signifies a "bear trap".</p>
                           <ul className="list-disc list-inside">
                                <li>Starts with an "Inside Bar" (a bar contained within the previous "Mother Bar").</li>
                                <li>Price then breaks <strong>BELOW</strong> the Mother Bar's low, trapping sellers.</li>
                                <li>It quickly <strong>REVERSES</strong> and closes back inside the Mother Bar's range, often as a bullish EXE bar.</li>
                           </ul>
                        </InfoSection>
                         <div className="border-t border-slate-800"></div>
                        <InfoSection title="Bearish Force Strike" visual={<CandlestickPattern {...examplePatterns[PatternType.BearishFS]} showLevels={true} />} >
                           <p>A bearish reversal pattern that signifies a "bull trap".</p>
                           <ul className="list-disc list-inside">
                                <li>Starts with an "Inside Bar".</li>
                                <li>Price then breaks <strong>ABOVE</strong> the Mother Bar's high, trapping buyers.</li>
                                <li>It then quickly <strong>REVERSES</strong> and closes back inside the Mother Bar's range, often as a bearish EXE bar.</li>
                           </ul>
                        </InfoSection>
                    </div>
                </section>
                
                <div className="border-t border-slate-700/50"></div>
                
                <section>
                    <h3 className="text-2xl font-bold text-indigo-400 border-b border-indigo-400/30 pb-2 mb-6">Trading with Force Strikes: Context is Key</h3>
                    <div className="space-y-8">
                        <InfoSection title="Uptrend Continuation">
                           <p>A high-probability setup for entering an existing uptrend.</p>
                           <ul className="list-disc list-inside">
                                <li>Price is in a clear uptrend (e.g., above the 50 SMA).</li>
                                <li>A <strong>Bullish FS</strong> appears as price retraces to test a key moving average (like the 20 or 50 SMA), indicating the pullback is likely over.</li>
                           </ul>
                        </InfoSection>
                        <div className="border-t border-slate-800"></div>
                        <InfoSection title="Downtrend Continuation">
                           <p>A high-probability setup for entering an existing downtrend.</p>
                           <ul className="list-disc list-inside">
                               <li>Price is in a clear downtrend (e.g., below the 50 SMA).</li>
                               <li>A <strong>Bearish FS</strong> appears as price rallies to test a key moving average, signaling a continuation of the downtrend.</li>
                           </ul>
                        </InfoSection>
                        <div className="border-t border-slate-800"></div>
                        <InfoSection title="Force Strike at Swing Points" visual={<CandlestickPattern {...examplePatterns['BullishFSAtSwingPoint']} showLevels={true} />} >
                           <p>Identifies a potential reversal at a major market turning point.</p>
                           <ul className="list-disc list-inside">
                               <li>First, a clear swing high (for bearish) or swing low (for bullish) is established. This level is key resistance/support.</li>
                               <li>Price returns to test this level.</li>
                               <li>A <strong>Force Strike</strong> forms right at this key level, suggesting the swing point will hold and price will reverse.</li>
                           </ul>
                        </InfoSection>
                    </div>
                </section>

                <div className="border-t border-slate-700/50"></div>

                <section>
                    <h3 className="text-2xl font-bold text-indigo-400 border-b border-indigo-400/30 pb-2 mb-6">Advanced Reversal Strategy: UR1 & DR1</h3>
                    <p className="text-slate-300 mb-6">UR1 and DR1 are distinct reversal patterns that identify early distribution or accumulation at key market turning points. They are different from a Force Strike.</p>
                    <div className="space-y-8">
                        <InfoSection title="Upside Reversal 1 (UR1)" visual={<CandlestickPattern {...examplePatterns[PatternType.UpsideReversal1]} showLevels={true} />} >
                           <p>A bearish reversal pattern indicating distribution (selling) near a peak.</p>
                           <ul className="list-disc list-inside">
                                <li>Establishes a swing high (Point X) and swing low (Point Y).</li>
                                <li>A "Majority Flush Up" move starts from below the 50% line between X and Y to test the Point X resistance.</li>
                                <li>Within 4 bars, a <strong>Bearish EXE</strong> bar forms and closes at or below the Point X level, confirming the reversal.</li>
                           </ul>
                        </InfoSection>
                         <div className="border-t border-slate-800"></div>
                        <InfoSection title="Downside Reversal 1 (DR1)" visual={<CandlestickPattern {...examplePatterns[PatternType.DownsideReversal1]} showLevels={true} />} >
                           <p>A bullish reversal pattern indicating accumulation (buying) near a bottom.</p>
                           <ul className="list-disc list-inside">
                                <li>Establishes a swing low (Point X) and swing high (Point Y).</li>
                                <li>A "Majority Flush Down" move starts from above the 50% line between X and Y to test the Point X support.</li>
                                <li>Within 4 bars, a <strong>Bullish EXE</strong> bar forms and closes at or above the Point X level, confirming the reversal.</li>
                           </ul>
                        </InfoSection>
                    </div>
                </section>
            </div>
        </div>
    </div>
  );
};

export default InfoModal;