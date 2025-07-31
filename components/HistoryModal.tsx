import React from 'react';
import type { HistoryEntry } from '../types.ts';
import Candlestick from './Candlestick.tsx';
import CandlestickPattern from './CandlestickPattern.tsx';
import ChartWithAxis from './ChartWithAxis.tsx';
import { CheckIcon, XIcon } from './icons.tsx';

interface HistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  history: HistoryEntry[];
  showLevels: boolean;
}

const HistoryRow: React.FC<{ entry: HistoryEntry; showLevels: boolean }> = ({ entry, showLevels }) => {
  const { bar, pattern, userAnswer, isCorrect, correctAnswer } = entry;

  return (
    <li className="flex items-center gap-4 p-3 bg-slate-800/70 rounded-lg">
      <div className="w-48 h-24 flex-shrink-0 bg-slate-900/50 rounded-md p-1">
        <ChartWithAxis>
            {bar && <div className="w-12 h-full mx-auto"><Candlestick bar={bar} /></div>}
            {pattern && <CandlestickPattern 
                          pattern={pattern.pattern} 
                          lpLevel={pattern.lpLevel} 
                          secondaryLpLevel={pattern.secondaryLpLevel}
                          showLevels={showLevels}
                          lpSourceIndex={pattern.lpSourceIndex}
                          secondaryLpSourceIndex={pattern.secondaryLpSourceIndex}
                          sma20={pattern.sma20}
                          sma50={pattern.sma50}
                        />}
        </ChartWithAxis>
      </div>
      <div className="flex-grow text-left text-sm">
        {isCorrect ? (
          <p className="font-bold text-green-400">Correct: {userAnswer}</p>
        ) : (
          <div>
            <p className="text-red-400">
              <span className="font-bold">Your answer: </span> 
              {userAnswer === null ? <span className="italic">Time ran out</span> : userAnswer}
            </p>
            <p className="text-slate-300">
              <span className="font-bold">Correct answer: </span> 
              {correctAnswer}
            </p>
          </div>
        )}
      </div>
      <div className="flex-shrink-0">
        {isCorrect ? <CheckIcon className="w-8 h-8 text-green-500" /> : <XIcon className="w-8 h-8 text-red-500" />}
      </div>
    </li>
  );
};

const HistoryModal: React.FC<HistoryModalProps> = ({ isOpen, onClose, history, showLevels }) => {
  if (!isOpen) return null;

  return (
    <div 
        className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
        onClick={onClose}
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-modal-title"
    >
      <div 
            className="bg-slate-900 border border-slate-700 rounded-2xl p-6 md:p-8 max-w-xl w-full max-h-[90vh] flex flex-col"
            onClick={e => e.stopPropagation()}
        >
        <div className="flex justify-between items-center mb-6 flex-shrink-0">
            <h2 id="history-modal-title" className="text-3xl font-bold text-white">Answer History</h2>
            <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close history">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
        </div>
        
        <div className="overflow-y-auto pr-2 -mr-2">
            {history.length > 0 ? (
                <ul className="space-y-3">
                    {history.map((entry, index) => (
                        <HistoryRow key={index} entry={entry} showLevels={showLevels} />
                    ))}
                </ul>
            ) : (
                <div className="text-center text-slate-400 py-12">
                    <p>No history yet.</p>
                    <p>Start a new game to see your results here.</p>
                </div>
            )}
        </div>
         <div className="mt-8 text-center flex-shrink-0">
            <button onClick={onClose} className="bg-cyan-500 hover:bg-cyan-600 text-white font-bold py-2 px-6 rounded-full text-lg transition-transform transform hover:scale-105">
                Close
            </button>
        </div>
      </div>
    </div>
  );
};

export default HistoryModal;