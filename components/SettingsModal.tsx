import React from 'react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  settings: {
    timeLimit: number;
  };
  onSettingsChange: (newSettings: Partial<{ timeLimit: number }>) => void;
}

const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose, settings, onSettingsChange }) => {
  if (!isOpen) return null;

  const handleTimeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSettingsChange({ timeLimit: Number(e.target.value) });
  };
  
  return (
    <div 
        className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4"
        onClick={onClose}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-modal-title"
    >
      <div 
          className="bg-slate-900 border border-slate-700 rounded-2xl p-6 md:p-8 max-w-md w-full" 
          onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-6">
          <h2 id="settings-modal-title" className="text-3xl font-bold text-white">Settings</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close settings">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="space-y-8">
          {/* Time Limit Setting */}
          <div>
            <label htmlFor="timeLimit" className="block text-lg font-medium text-slate-300 mb-2">
              Time per question: <span className="font-bold text-cyan-400">{settings.timeLimit / 1000}s</span>
            </label>
            <input
              id="timeLimit"
              type="range"
              min="5000"
              max="20000"
              step="1000"
              value={settings.timeLimit}
              onChange={handleTimeChange}
              className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:bg-cyan-500 [&::-moz-range-thumb]:bg-cyan-500"
            />
          </div>
        </div>
        
         <div className="mt-10 text-center">
            <button onClick={onClose} className="bg-cyan-500 hover:bg-cyan-600 text-white font-bold py-2 px-6 rounded-full text-lg transition-transform transform hover:scale-105">
                Close
            </button>
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;