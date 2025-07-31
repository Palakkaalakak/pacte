export enum GameCategory {
  Types = 'Bar Types',
  Patterns = 'Bar Patterns'
}

export enum BarType {
  Pin = 'Pin Bar',
  Mark = 'Mark Up/Down Bar',
  IceCream = 'Ice Cream Bar',
  Other = 'Other'
}

export enum PatternType {
  BullishFS = 'Bullish Force Strike',
  BearishFS = 'Bearish Force Strike',
  UpsideReversal1 = 'Upside Reversal 1',
  DownsideReversal1 = 'Downside Reversal 1',
  Other = 'Other Pattern',
}

export enum GameMode {
  Detailed = 'Detailed',
  Simple = 'Simple',
  BaseFS = 'Base FS',
  ContinuationFS = 'Continuation FS',
  FSAtSwingPoints = 'FS at Swing Points',
  Reversal1 = 'Reversal 1',
  ComprehensiveMix = 'Comprehensive Mix',
}

export enum Difficulty {
  Basic = 'Basic',
  Medium = 'Medium',
  Advanced = 'Advanced',
}

export enum SimpleAnswer {
  Exe = 'EXE Bar',
  NonExe = 'Non-EXE Bar',
}

export interface BarData {
  open: number;
  high: number;
  low: number;
  close: number;
  type: BarType; // The underlying type of the single bar
}

export interface PatternData {
  pattern: BarData[];
  type: PatternType;
  lpLevel?: number; // Optional level for support/resistance lines
  lpSourceIndex?: number; // Optional index of the bar that creates the lpLevel
  secondaryLpLevel?: number; // For UR1/DR1 "Point Y"
  secondaryLpSourceIndex?: number; // Index for Point Y
  sma20?: (number | undefined)[];
  sma50?: (number | undefined)[];
}

export enum GameState {
  Idle,
  SelectingMode, // New state for choosing game mode within a category
  Playing,
  Result
}

export interface HistoryEntry {
  bar?: BarData;
  pattern?: PatternData;
  userAnswer: BarType | SimpleAnswer | PatternType | null;
  isCorrect: boolean;
  correctAnswer: string;
}