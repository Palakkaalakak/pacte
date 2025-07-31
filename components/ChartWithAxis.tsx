import React from 'react';

const YAxis: React.FC = () => {
    // The viewBox height. We'll set it to 220, representing a range from -110 to 110.
    const viewBoxHeight = 220;
    // The labels we want to display on the axis.
    const labels = [100, 50, 0, -50, -100];

    return (
        <svg 
            // Use a viewBox to make the SVG scalable.
            // viewBox="x y width height"
            // We set y to -110, so the coordinate system inside the SVG runs from -110 (top) to 110 (bottom).
            // This is the standard SVG coordinate system (Y increases downwards).
            viewBox={`0 ${-viewBoxHeight / 2} 40 ${viewBoxHeight}`} 
            className="w-10 h-full flex-shrink-0"
            preserveAspectRatio="xMidYMid meet" // Ensures it scales nicely
        >
             {/* We flip the Y-axis for the entire group to match our "Y-up" world coordinates */}
            <g transform="scale(1, -1)">
                {labels.map(label => (
                    <g key={label} className="text-xs text-slate-500">
                        <line
                            x1="30"
                            y1={label} // Use world coordinate directly
                            x2="40"
                            y2={label}
                            stroke="currentColor"
                            strokeWidth="1.5"
                            vectorEffect="non-scaling-stroke" // Prevents stroke from getting thicker/thinner on scale
                        />
                         {/* We must flip the text back so it's not upside-down */}
                        <text
                            transform={`translate(25, ${label}) scale(1, -1)`}
                            textAnchor="end"
                            alignmentBaseline="middle"
                            fill="currentColor"
                            style={{ fontSize: '10px' }} 
                        >
                            {label}
                        </text>
                    </g>
                ))}
            </g>
        </svg>
    );
};


const ChartWithAxis: React.FC<{children: React.ReactNode}> = ({ children }) => {
  return (
    <div className="flex items-stretch h-full w-full">
      <YAxis />
      <div className="flex-grow h-full">
        {children}
      </div>
    </div>
  );
};

export default ChartWithAxis;