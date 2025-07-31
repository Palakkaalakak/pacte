
import React from 'react';
import type { BarData } from '../types.ts';

interface CandlestickProps {
  bar: BarData;
}

const Candlestick: React.FC<CandlestickProps> = ({ bar }) => {
  const { open, high, low, close } = bar;

  const isBullish = close >= open;
  const color = isBullish ? 'text-green-500' : 'text-red-500';
  const fill = isBullish ? 'fill-green-500' : 'fill-red-500';

  const bodyTop = Math.max(open, close);
  const bodyBottom = Math.min(open, close);
  const bodyHeight = bodyTop - bodyBottom;
  
  // The viewBox height. Should match the YAxis.
  const viewBoxHeight = 220;

  return (
    <svg 
      // viewBox="x y width height"
      // x is centered, y starts from -110 to cover the full range.
      viewBox={`0 ${-viewBoxHeight / 2} 100 ${viewBoxHeight}`} 
      className="w-full h-full" 
      preserveAspectRatio="xMidYMid meet"
      aria-label={`Candlestick chart: open ${open}, high ${high}, low ${low}, close ${close}`}
    >
      {/* We need to flip the Y coordinates of all our data points because SVG's Y-axis is inverted. */}
      <g transform="scale(1, -1)" className={color}>
        {/* Upper Wick */}
        <line x1="50" y1={high} x2="50" y2={bodyTop} stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        {/* Lower Wick */}
        <line x1="50" y1={low} x2="50" y2={bodyBottom} stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        {/* Body - Drawn on top of wicks to ensure clean joins */}
        <rect x="25" y={bodyBottom} width="50" height={bodyHeight > 0 ? bodyHeight : 0.1} className={fill} />
      </g>
    </svg>
  );
};

export default Candlestick;
