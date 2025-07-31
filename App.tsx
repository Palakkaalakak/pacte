import React, { useState, useEffect, useCallback, useRef } from 'react';
import { GameState, BarType, BarData, HistoryEntry, GameMode, SimpleAnswer, GameCategory, PatternType, PatternData, Difficulty } from './types.ts';
import { generateRandomBar, generatePinBar, generateMarkBar, generateIceCreamBar, generateExeBar, generateOtherBar, generateRandomPattern, generateRandomTrendPattern, generateFSAtSwingPointPattern, generateRandomReversal1Pattern } from './services/barGenerator.ts';
import Candlestick from './components/Candlestick.tsx';
import CandlestickPattern from './components/CandlestickPattern.tsx';
import ChartWithAxis from './components/ChartWithAxis.tsx';
import { CheckIcon, XIcon, HistoryIcon, PauseIcon, HomeIcon, BackArrowIcon, SettingsIcon, DottedLineIcon, PlayIcon } from './components/icons.tsx';
import InfoModal from './components/InfoModal.tsx';
import HistoryModal from './components/HistoryModal.tsx';
import SettingsModal from './components/SettingsModal.tsx';
import Logo from './components/Logo.tsx';
import { playSound, SoundType as SoundTypeEnum } from './services/sounds.ts';

const RESULT_DELAY_MS = 1500;
const TIMEOUT_RESULT_DELAY_MS = 5000;
const SKIP_THRESHOLD = 3;
const FAILURE_THRESHOLD = 3;
const REHAB_SUCCESS_GOAL = 3;
const MAX_HISTORY_LENGTH = 50;
const MAX_CONSECUTIVE_SIMPLE = 2;


const EXE_BAR_TYPES = [BarType.Pin, BarType.Mark, BarType.IceCream];
const FS_PATTERN_TYPES = [PatternType.BullishFS, PatternType.BearishFS, PatternType.Other];
const R1_PATTERN_TYPES = [PatternType.UpsideReversal1, PatternType.DownsideReversal1, PatternType.Other];

export default function App() {
  const [gameState, setGameState] = useState<GameState>(GameState.Idle);
  const [gameCategory, setGameCategory] = useState<GameCategory | null>(null);
  const [gameMode, setGameMode] = useState<GameMode | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty | null>(null);
  const [score, setScore] = useState(0);
  const [currentBar, setCurrentBar] = useState<BarData | null>(null);
  const [currentPattern, setCurrentPattern] = useState<PatternData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [timeLeft, setTimeLeft] = useState(10000);
  const [isCorrect, setIsCorrect] = useState<boolean | null>(null);
  const [correctAnswer, setCorrectAnswer] = useState<string>('');
  const [isInfoModalOpen, setIsInfoModalOpen] = useState(false);
  const [isHistoryModalOpen, setIsHistoryModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [showLevels, setShowLevels] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [settings, setSettings] = useState({ timeLimit: 10000 });
  
  const skippedCountsRef = useRef<Record<string, number>>({ [BarType.Pin]: 0, [BarType.Mark]: 0, [BarType.IceCream]: 0 });
  const failureCountsRef = useRef<Record<string, number>>({ [BarType.Pin]: 0, [BarType.Mark]: 0, [BarType.IceCream]: 0 });
  const rehabSuccessCountsRef = useRef<Record<string, number>>({ [BarType.Pin]: 0, [BarType.Mark]: 0, [BarType.IceCream]: 0 });
  const simpleModeConsecutiveRef = useRef<{ type: SimpleAnswer | null; count: number }>({ type: null, count: 0 });
  const nextTurnTimeoutRef = useRef<number | null>(null);
  
  const addToHistory = (entry: HistoryEntry) => {
    setHistory(prev => [entry, ...prev].slice(0, MAX_HISTORY_LENGTH));
  };

  const goToMainMenu = useCallback(() => {
      setGameState(GameState.Idle);
      setGameCategory(null);
      setGameMode(null);
      setDifficulty(null);
      if (nextTurnTimeoutRef.current) clearTimeout(nextTurnTimeoutRef.current);
  }, []);

  const nextTurn = useCallback((mode: GameMode | null) => {
    setIsCorrect(null);
    setCurrentBar(null);
    setCurrentPattern(null);
    setIsLoading(true);
    if (nextTurnTimeoutRef.current) clearTimeout(nextTurnTimeoutRef.current);

    if (!mode) {
        setGameState(GameState.Idle);
        setIsLoading(false);
        return;
    }
    
    // Use a short timeout to allow the "Loading..." state to render
    setTimeout(() => {
      let barToSet: BarData | null = null;
      let patternToSet: PatternData | null = null;

      if (mode === GameMode.BaseFS) {
          patternToSet = generateRandomPattern();
      } else if (mode === GameMode.ContinuationFS) {
          patternToSet = generateRandomTrendPattern();
      } else if (mode === GameMode.FSAtSwingPoints) {
          patternToSet = generateFSAtSwingPointPattern();
      } else if (mode === GameMode.Reversal1) {
          patternToSet = generateRandomReversal1Pattern();
      } else if (mode === GameMode.Detailed) {
          let newBar: BarData;
          const strugglingTypes = Object.entries(failureCountsRef.current).filter(([, count]) => count >= FAILURE_THRESHOLD).map(([type]) => type as BarType);
          const skippedTooMany = Object.entries(skippedCountsRef.current).filter(([, count]) => count >= SKIP_THRESHOLD).map(([type]) => type as BarType);
          
          if (strugglingTypes.length > 0) {
              const forcedType = strugglingTypes[0];
              if (forcedType === BarType.Pin) newBar = generatePinBar({ isBullish: Math.random() > 0.5 });
              else if (forcedType === BarType.Mark) newBar = generateMarkBar({ isBullish: Math.random() > 0.5 });
              else newBar = generateIceCreamBar({ isBullish: Math.random() > 0.5 });
          } else if (skippedTooMany.length > 0) {
              const forcedType = skippedTooMany[0];
              if (forcedType === BarType.Pin) newBar = generatePinBar({ isBullish: Math.random() > 0.5 });
              else if (forcedType === BarType.Mark) newBar = generateMarkBar({ isBullish: Math.random() > 0.5 });
              else newBar = generateIceCreamBar({ isBullish: Math.random() > 0.5 });
          } else {
              newBar = generateRandomBar();
          }
          
          EXE_BAR_TYPES.forEach(type => {
              if (type === newBar.type) {
                  skippedCountsRef.current[type] = 0;
              } else {
                  skippedCountsRef.current[type]++;
              }
          });
          barToSet = newBar;
      } else if (mode === GameMode.Simple) {
          let newBar: BarData;
          const consecutive = simpleModeConsecutiveRef.current;
          let nextBarIsExe: boolean;

          if (consecutive.count >= MAX_CONSECUTIVE_SIMPLE) {
              nextBarIsExe = consecutive.type === SimpleAnswer.NonExe;
          } else {
              nextBarIsExe = Math.random() > 0.5;
          }

          if (nextBarIsExe) {
              newBar = generateExeBar({ isBullish: Math.random() > 0.5 });
              simpleModeConsecutiveRef.current = { type: SimpleAnswer.Exe, count: consecutive.type === SimpleAnswer.Exe ? consecutive.count + 1 : 1 };
          } else {
              newBar = generateOtherBar();
              simpleModeConsecutiveRef.current = { type: SimpleAnswer.NonExe, count: consecutive.type === SimpleAnswer.NonExe ? consecutive.count + 1 : 1 };
          }
          barToSet = newBar;
      } 

      setCurrentBar(barToSet);
      setCurrentPattern(patternToSet);
      setTimeLeft(settings.timeLimit);
      setGameState(GameState.Playing);
      setIsLoading(false);
    }, 50);

  }, [settings.timeLimit]);
  
  const handleSelectCategory = (category: GameCategory) => {
    setGameCategory(category);
    setDifficulty(null);
    setGameState(GameState.SelectingMode);
  };

  const handleStart = (mode: GameMode) => {
    setGameMode(mode);
    setScore(0);
    setHistory([]);
    setShowLevels(mode === GameMode.FSAtSwingPoints || mode === GameMode.Reversal1);
    skippedCountsRef.current = { [BarType.Pin]: 0, [BarType.Mark]: 0, [BarType.IceCream]: 0 };
    failureCountsRef.current = { [BarType.Pin]: 0, [BarType.Mark]: 0, [BarType.IceCream]: 0 };
    rehabSuccessCountsRef.current = { [BarType.Pin]: 0, [BarType.Mark]: 0, [BarType.IceCream]: 0 };
    simpleModeConsecutiveRef.current = { type: null, count: 0 };
    nextTurn(mode);
  };
  
  const handleTimeout = useCallback(() => {
    if (gameState !== GameState.Playing || isLoading) return;
    playSound(SoundTypeEnum.Timeout);
    const currentMode = gameMode;
    if (!currentBar && !currentPattern) return;

    setGameState(GameState.Result);
    setIsCorrect(false);
    
    let answerForHistory: string;
    let historyEntry: HistoryEntry;

    if (currentPattern) {
        answerForHistory = currentPattern!.type;
        historyEntry = { pattern: currentPattern!, userAnswer: null, isCorrect: false, correctAnswer: answerForHistory };
    } else { // Bar modes
        const barType = currentBar!.type;
        if (currentMode === GameMode.Detailed) {
            answerForHistory = barType;
             if (EXE_BAR_TYPES.includes(barType)) {
                failureCountsRef.current[barType]++;
                rehabSuccessCountsRef.current[barType] = 0;
            }
        } else { // Simple Mode
            answerForHistory = EXE_BAR_TYPES.includes(barType) ? SimpleAnswer.Exe : SimpleAnswer.NonExe;
        }
        historyEntry = { bar: currentBar!, userAnswer: null, isCorrect: false, correctAnswer: answerForHistory };
    }
    
    setCorrectAnswer(answerForHistory);
    addToHistory(historyEntry);

    if (nextTurnTimeoutRef.current) clearTimeout(nextTurnTimeoutRef.current);
    nextTurnTimeoutRef.current = window.setTimeout(() => nextTurn(currentMode), TIMEOUT_RESULT_DELAY_MS);
  }, [gameState, gameMode, currentBar, currentPattern, isLoading, nextTurn]);

  const handleAnswer = (answer: BarType | SimpleAnswer | PatternType) => {
    if (gameState !== GameState.Playing) return;

    let isAnswerCorrect: boolean;
    let correctAnswerForDisplay: string;
    let historyEntry: HistoryEntry;
    
    const isPatternMode = !!currentPattern;

    if (isPatternMode) {
        isAnswerCorrect = answer === currentPattern!.type;
        correctAnswerForDisplay = currentPattern!.type;
        historyEntry = { pattern: currentPattern!, userAnswer: answer as PatternType, isCorrect: isAnswerCorrect, correctAnswer: correctAnswerForDisplay };
    } else { // Bar modes
        const actualBarType = currentBar!.type;
        if (gameMode === GameMode.Detailed) {
            isAnswerCorrect = answer === actualBarType;
            correctAnswerForDisplay = actualBarType!;
            if (EXE_BAR_TYPES.includes(actualBarType!)) {
                const barT = actualBarType as BarType.Pin | BarType.Mark | BarType.IceCream;
                if (isAnswerCorrect) {
                     if (failureCountsRef.current[barT] >= FAILURE_THRESHOLD) {
                        rehabSuccessCountsRef.current[barT]++;
                        if (rehabSuccessCountsRef.current[barT] >= REHAB_SUCCESS_GOAL) {
                            failureCountsRef.current[barT] = 0;
                            rehabSuccessCountsRef.current[barT] = 0;
                        }
                    } else {
                         failureCountsRef.current[barT] = Math.max(0, failureCountsRef.current[barT] - 1);
                    }
                } else {
                    failureCountsRef.current[barT]++;
                    rehabSuccessCountsRef.current[barT] = 0;
                }
            }
        } else { // Simple mode
            const isExe = EXE_BAR_TYPES.includes(actualBarType!);
            isAnswerCorrect = (isExe && answer === SimpleAnswer.Exe) || (!isExe && answer === SimpleAnswer.NonExe);
            correctAnswerForDisplay = isExe ? SimpleAnswer.Exe : SimpleAnswer.NonExe;
        }
        historyEntry = { bar: currentBar!, userAnswer: answer as BarType | SimpleAnswer, isCorrect: isAnswerCorrect, correctAnswer: correctAnswerForDisplay };
    }

    if (isAnswerCorrect) {
        setScore(s => s + 10);
        playSound(SoundTypeEnum.Correct);
    } else {
        playSound(SoundTypeEnum.Incorrect);
    }
    
    setIsCorrect(isAnswerCorrect);
    setCorrectAnswer(correctAnswerForDisplay);
    setGameState(GameState.Result);
    addToHistory(historyEntry);

    if (nextTurnTimeoutRef.current) clearTimeout(nextTurnTimeoutRef.current);
    nextTurnTimeoutRef.current = window.setTimeout(() => nextTurn(gameMode), RESULT_DELAY_MS);
  };
  
  useEffect(() => {
    if (gameState !== GameState.Playing || isPaused || isLoading) {
      return;
    }
    const timer = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 100) {
          clearInterval(timer);
          handleTimeout();
          return 0;
        }
        return prev - 100;
      });
    }, 100);
    return () => clearInterval(timer);
  }, [gameState, isPaused, isLoading, handleTimeout]);

  const handleSettingsChange = (newSettings: Partial<{ timeLimit: number }>) => {
    setSettings(prev => ({ ...prev, ...newSettings }));
  };

  const resetToModeSelect = useCallback(() => {
      setGameState(GameState.SelectingMode);
      setGameMode(null);
      setDifficulty(null);
      if (nextTurnTimeoutRef.current) clearTimeout(nextTurnTimeoutRef.current);
  }, []);

  const renderHeader = () => {
    const isPatternMode = gameCategory === GameCategory.Patterns;
    return (
        <header className="flex justify-between items-center mb-4 p-2 sm:p-4 bg-slate-800/50 rounded-xl border border-slate-700">
            <div className="flex items-center gap-2 flex-1 justify-start">
                <button onClick={() => setIsSettingsModalOpen(true)} title="Settings" className="text-slate-400 hover:text-white transition-colors p-2 rounded-full hover:bg-slate-700">
                    <SettingsIcon className="w-6 h-6" />
                </button>
                {gameState !== GameState.Idle && (
                    <button onClick={goToMainMenu} title="Home" className="text-slate-400 hover:text-white transition-colors p-2 rounded-full hover:bg-slate-700">
                        <HomeIcon className="w-6 h-6" />
                    </button>
                )}
                {gameState === GameState.Playing && (
                    <button onClick={resetToModeSelect} title="Back to Mode Select" className="text-slate-400 hover:text-white transition-colors p-2 rounded-full hover:bg-slate-700">
                        <BackArrowIcon className="w-6 h-6" />
                    </button>
                )}
            </div>

            <div className="text-lg sm:text-xl font-semibold bg-slate-700/50 px-4 py-2 rounded-lg whitespace-nowrap">Score: <span className="text-green-400 font-bold">{score}</span></div>

            <div className="flex items-center gap-2 flex-1 justify-end">
                {gameState === GameState.Playing && (
                    <button onClick={() => setIsPaused(p => !p)} title={isPaused ? "Resume" : "Pause"} className="text-slate-400 hover:text-white transition-colors p-2 rounded-full hover:bg-slate-700">
                        {isPaused ? <PlayIcon className="w-6 h-6" /> : <PauseIcon className="w-6 h-6" />}
                    </button>
                )}
                {gameState !== GameState.Idle && gameMode !== null && (
                    <button onClick={() => setIsHistoryModalOpen(true)} title="History" className="text-slate-400 hover:text-white transition-colors p-2 rounded-full hover:bg-slate-700">
                        <HistoryIcon className="w-6 h-6" />
                    </button>
                )}
                {isPatternMode && gameState !== GameState.Idle && (
                    <button onClick={() => setShowLevels(s => !s)} title="Toggle Levels" className={`p-2 rounded-full transition-colors ${showLevels ? 'text-yellow-400 bg-slate-700' : 'text-slate-400 hover:text-white hover:bg-slate-700'}`}>
                        <DottedLineIcon className="w-6 h-6" />
                    </button>
                )}
            </div>
        </header>
    );
  }

  const renderMainMenu = () => (
    <div className="text-center animate-fade-in">
      <Logo className="w-24 h-24 mx-auto mb-6" />
      <h1 className="text-4xl sm:text-5xl font-extrabold text-white mb-4">Price Action Pattern Trainer</h1>
      <p className="text-slate-400 mb-10 text-lg">Select a category to begin.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <button onClick={() => handleSelectCategory(GameCategory.Types)} className="bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105">
          {GameCategory.Types}
        </button>
        <button onClick={() => handleSelectCategory(GameCategory.Patterns)} className="bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105">
          {GameCategory.Patterns}
        </button>
      </div>
      <button onClick={() => { setIsInfoModalOpen(true); }} className="mt-8 text-cyan-400 hover:text-cyan-300">
        Open Pattern & Strategy Guide
      </button>
    </div>
  );
  
  const renderModeSelectMenu = () => (
    <div className="text-center animate-fade-in">
        <div className="flex items-center justify-center mb-4">
            <button 
                onClick={gameCategory === GameCategory.Patterns && difficulty ? () => setDifficulty(null) : goToMainMenu} 
                title="Back" 
                className="text-slate-400 hover:text-white transition-colors p-2 rounded-full hover:bg-slate-700 mr-4"
            >
                <BackArrowIcon className="w-6 h-6" />
            </button>
            <h1 className="text-4xl sm:text-5xl font-extrabold text-white">
                {gameCategory === GameCategory.Types 
                    ? 'Bar Type Modes' 
                    : difficulty 
                        ? `${difficulty} Pattern Modes` 
                        : 'Pattern Difficulty'
                }
            </h1>
        </div>
      <p className="text-slate-400 mb-10 text-lg">
        {gameCategory === GameCategory.Patterns && !difficulty ? 'Select a difficulty level.' : 'Choose how you want to be tested.'}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {gameCategory === GameCategory.Types ? (
            <div className="sm:col-span-2 lg:col-span-3 flex flex-col sm:flex-row justify-center items-center gap-6">
                <button onClick={() => handleStart(GameMode.Detailed)} className="bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105 w-full sm:w-auto">
                    Detailed Recognition
                </button>
                <button onClick={() => handleStart(GameMode.Simple)} className="bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105 w-full sm:w-auto">
                    Simple Distinction
                </button>
            </div>
        ) : !difficulty ? (
             <>
                <button onClick={() => setDifficulty(Difficulty.Basic)} className="bg-green-600 hover:bg-green-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105">
                    {Difficulty.Basic}
                </button>
                <button onClick={() => setDifficulty(Difficulty.Medium)} className="bg-yellow-600 hover:bg-yellow-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105">
                    {Difficulty.Medium}
                </button>
                <button disabled className="bg-red-600 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform opacity-50 cursor-not-allowed">
                    {Difficulty.Advanced} (Soon)
                </button>
            </>
        ) : difficulty === Difficulty.Basic ? (
            <>
                <button onClick={() => handleStart(GameMode.BaseFS)} className="bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105">
                    Base FS
                </button>
                <button onClick={() => handleStart(GameMode.ContinuationFS)} className="bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105">
                    Continuation FS
                </button>
                <button onClick={() => handleStart(GameMode.FSAtSwingPoints)} className="bg-rose-600 hover:bg-rose-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105 sm:col-span-2 lg:col-span-1">
                    FS at Swing Points
                </button>
            </>
        ) : difficulty === Difficulty.Medium ? (
            <div className="sm:col-span-2 lg:col-span-3">
                <button onClick={() => handleStart(GameMode.Reversal1)} className="bg-yellow-600 hover:bg-yellow-500 text-white font-bold py-4 px-6 rounded-lg text-xl transition-transform transform hover:scale-105 w-full">
                    {GameMode.Reversal1}
                </button>
            </div>
        ) : (
            <p className="text-slate-400 col-span-full">This difficulty is coming soon!</p>
        )}
      </div>
    </div>
  );

  const renderGame = () => {
    const isPatternMode = !!currentPattern;
    
    const getAnswerOptions = () => {
        if (!isPatternMode) {
            return gameMode === GameMode.Detailed ? Object.values(BarType) : Object.values(SimpleAnswer);
        }
        switch(gameMode) {
            case GameMode.Reversal1:
                return R1_PATTERN_TYPES;
            case GameMode.BaseFS:
            case GameMode.ContinuationFS:
            case GameMode.FSAtSwingPoints:
            default:
                return FS_PATTERN_TYPES;
        }
    };

    const answerOptions = getAnswerOptions();
    
    const getGridClass = () => {
        switch (answerOptions.length) {
            case 4: return 'grid-cols-2 lg:grid-cols-4'; // Detailed
            case 3: return 'grid-cols-1 sm:grid-cols-3'; // FS and Reversal1
            default: return 'grid-cols-2'; // Simple, etc.
        }
    };

    return (
      <div className="w-full">
        <div className="h-2 bg-slate-700 rounded-full mb-4 overflow-hidden">
          <div className="h-full bg-cyan-400 transition-all duration-100 ease-linear" style={{ width: `${(timeLeft / settings.timeLimit) * 100}%` }}/>
        </div>
        <div className="h-64 md:h-80 w-full mb-6 relative">
             <ChartWithAxis>
              {isPatternMode 
                ? <CandlestickPattern 
                    pattern={currentPattern?.pattern ?? []} 
                    lpLevel={currentPattern?.lpLevel} 
                    secondaryLpLevel={currentPattern?.secondaryLpLevel}
                    showLevels={showLevels || gameMode === GameMode.FSAtSwingPoints || gameMode === GameMode.Reversal1}
                    lpSourceIndex={currentPattern?.lpSourceIndex}
                    secondaryLpSourceIndex={currentPattern?.secondaryLpSourceIndex}
                    sma20={currentPattern?.sma20}
                    sma50={currentPattern?.sma50}
                  />
                : (currentBar && <div className="w-24 h-full mx-auto"><Candlestick bar={currentBar} /></div>)
              }
             </ChartWithAxis>
            {gameState === GameState.Result && (
                <div className={`absolute inset-0 flex items-center justify-center bg-black/50 rounded-lg text-3xl sm:text-5xl font-extrabold text-center p-4 ${isCorrect ? 'text-green-400' : 'text-red-400'}`}>
                    {isCorrect ? 'Correct!' : `Wrong! It's a ${correctAnswer}`}
                </div>
            )}
            {isPaused && (
                 <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 rounded-lg">
                    <h2 className="text-5xl font-extrabold text-white mb-6">Paused</h2>
                    <button onClick={() => setIsPaused(false)} className="bg-cyan-500 hover:bg-cyan-600 text-white font-bold py-3 px-8 rounded-full text-xl transition-transform transform hover:scale-105">Resume</button>
                </div>
            )}
        </div>
        <div className={`grid ${getGridClass()} gap-4`}>
          {answerOptions.map(option => (
            <button key={option} onClick={() => handleAnswer(option as any)} disabled={gameState === GameState.Result || isPaused} className="py-4 px-2 text-center rounded-lg font-semibold text-lg transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed bg-slate-700 hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-cyan-400">
              {option}
            </button>
          ))}
        </div>
      </div>
    );
  };

  const renderContent = () => {
    switch(gameState) {
      case GameState.Idle:
        return renderMainMenu();
      case GameState.SelectingMode:
        return renderModeSelectMenu();
      case GameState.Playing:
      case GameState.Result:
        if (isLoading) {
            return <div className="text-slate-400">Loading...</div>;
        }
        if (!currentBar && !currentPattern) {
            return <div className="text-slate-400">Loading...</div>;
        }
        return renderGame();
      default:
        return renderMainMenu();
    }
  };

  return (
    <div className="bg-slate-900 text-white min-h-screen flex flex-col items-center justify-center p-2 sm:p-4 font-sans antialiased">
      <div className="w-full max-w-4xl mx-auto">
        {renderHeader()}
        <main className="bg-slate-800 p-4 sm:p-6 rounded-2xl shadow-2xl relative min-h-[480px] sm:min-h-[550px] flex flex-col justify-center items-center border border-slate-700">
          {renderContent()}
        </main>
      </div>
      <InfoModal isOpen={isInfoModalOpen} onClose={() => setIsInfoModalOpen(false)} />
      <HistoryModal isOpen={isHistoryModalOpen} onClose={() => setIsHistoryModalOpen(false)} history={history} showLevels={showLevels} />
      <SettingsModal isOpen={isSettingsModalOpen} onClose={() => setIsSettingsModalOpen(false)} settings={settings} onSettingsChange={handleSettingsChange} />
    </div>
  );
}
