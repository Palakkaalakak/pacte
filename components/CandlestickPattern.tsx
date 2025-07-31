
import React from 'react';
import type { BarData } from '../types.ts';

interface CandlestickPatternProps {
  pattern: BarData[];
  className?: string;
  lpLevel?: number;
  lpSourceIndex?: number;
  secondaryLpLevel?: number;
  secondaryLpSourceIndex?: number;
  showLevels?: boolean;
  sma20?: (number | undefined)[];
  sma50?: (number | undefined)[];
}

// Re-implementing the bar drawing logic here for a single SVG context
const renderBarInPattern = (bar: BarData, xOffset: number, barWidth: number) => {
    const { open, high, low, close } = bar;
    const isBullish = close >= open;
    const color = isBullish ? 'text-green-500' : 'text-red-500';
    const fill = isBullish ? 'fill-green-500' : 'fill-red-500';

    const bodyTop = Math.max(open, close);
    const bodyBottom = Math.min(open, close);
    const bodyHeight = bodyTop - bodyBottom;
    const wickCenter = xOffset + barWidth / 2;

    return (
        <g key={`${xOffset}`} className={color}>
            {/* Upper Wick */}
            <line x1={wickCenter} y1={high} x2={wickCenter} y2={bodyTop} stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            {/* Lower Wick */}
            <line x1={wickCenter} y1={low} x2={wickCenter} y2={bodyBottom} stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            {/* Body - Drawn on top of wicks to ensure clean joins */}
            <rect x={xOffset} y={bodyBottom} width={barWidth} height={bodyHeight > 0 ? bodyHeight : 0.1} className={fill} />
        </g>
    );
};

const createSmaPath = (smaData: (number | undefined)[] | undefined, barUnitWidth: number): string => {
    if (!smaData) return "";
    let path = "";
    let firstPoint = true;
    
    smaData.forEach((point, index) => {
        if (point !== undefined) {
            const x = (index * barUnitWidth) + (barUnitWidth / 2);
            const y = point;
            if (firstPoint) {
                path += `M ${x} ${y}`;
                firstPoint = false;
            } else {
                path += ` L ${x} ${y}`;
            }
        }
    });

    return path;
}


const CandlestickPattern: React.FC<CandlestickPatternProps> = ({ pattern, className = '', lpLevel, lpSourceIndex, secondaryLpLevel, secondaryLpSourceIndex, showLevels, sma20, sma50 }) => {
  if (!pattern || pattern.length === 0) return null;
  
  const numBars = pattern.length;
  const barUnitWidth = Math.max(20, 400 / numBars); // Dynamic width
  const barBodyWidth = barUnitWidth * 0.6; 
  const barSpacing = barUnitWidth - barBodyWidth; 
  const totalWidth = barUnitWidth * numBars; 

  const viewBoxHeight = 220;

  const sma20path = createSmaPath(sma20, barUnitWidth);
  const sma50path = createSmaPath(sma50, barUnitWidth);
  
  const lpLineStartX = lpSourceIndex !== undefined ? (lpSourceIndex * barUnitWidth) + (barUnitWidth / 2) : 0;
  const secondaryLpLineStartX = secondaryLpSourceIndex !== undefined ? (secondaryLpSourceIndex * barUnitWidth) + (barUnitWidth / 2) : 0;

  return (
    <div className={`h-full w-full ${className}`}>
      <svg
        viewBox={`0 ${-viewBoxHeight / 2} ${totalWidth} ${viewBoxHeight}`}
        className="w-full h-full"
        preserveAspectRatio="xMinYMid meet"
      >
        <g transform="scale(1, -1)">
          {/* Render all bars */}
          {pattern.map((bar, index) => {
              const xOffset = index * barUnitWidth + (barSpacing / 2);
              return renderBarInPattern(bar, xOffset, barBodyWidth);
          })}
          
          {/* Render SMAs */}
          {sma20path && (
              <path d={sma20path} className="stroke-green-500" fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          )}
          {sma50path && (
              <path d={sma50path} className="stroke-yellow-400" fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
          )}

          {/* Render LP level line */}
          {showLevels && lpLevel !== undefined && (
            <line
              x1={lpLineStartX}
              y1={lpLevel}
              x2={totalWidth}
              y2={lpLevel}
              className="stroke-cyan-400"
              strokeWidth="1.5"
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />
          )}

          {/* Render Secondary LP level line */}
           {showLevels && secondaryLpLevel !== undefined && (
            <line
              x1={secondaryLpLineStartX}
              y1={secondaryLpLevel}
              x2={totalWidth}
              y2={secondaryLpLevel}
              className="stroke-cyan-400"
              strokeWidth="1.5"
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </g>
      </svg>
    </div>
  );
};

export default CandlestickPattern;