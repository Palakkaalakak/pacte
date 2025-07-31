import React from 'react';

const Logo: React.FC<{ className?: string }> = ({ className }) => (
    <svg 
        viewBox="0 0 100 100"
        className={className}
        aria-hidden="true"
    >
        <circle cx="50" cy="50" r="46" className="stroke-cyan-500 fill-slate-800" strokeWidth="4"/>
        <path d="M25 70 L40 50 L55 60 L75 35" className="stroke-green-500" strokeWidth="8" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
);

export default Logo;
