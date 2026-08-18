import React from "react";

export interface MSAJLogoProps extends React.SVGProps<SVGSVGElement> {
  size?: number | string;
  variant?: "theme" | "green" | "original" | "monochrome";
  primaryColor?: string;
  accentColor?: string;
  textColor?: string;
  glow?: boolean;
  className?: string;
}

/**
 * MSAJCE College Shield Vector Logo Component
 * 
 * Features:
 * - 100% Vector SVG recreating the official MSAJCE crest emblem.
 * - Perfectly adapts to Green theme or custom CSS variables (--primary / --primary-dark).
 * - Multi-variant support: "theme" (auto-adapts to green theme), "green", "original", or "monochrome".
 */
export const MSAJLogo: React.FC<MSAJLogoProps> = ({
  size = 36,
  variant = "theme",
  primaryColor,
  accentColor,
  textColor = "#FFFFFF",
  glow = false,
  className = "",
  style,
  ...props
}) => {
  // Determine fill colors based on requested variant
  let topFill = primaryColor;
  let bottomFill = accentColor;

  if (!topFill) {
    switch (variant) {
      case "green":
        topFill = "var(--primary)";
        break;
      case "original":
        topFill = "#005DA6"; // Classic MSAJ Navy Blue
        break;
      case "monochrome":
        topFill = "currentColor";
        break;
      case "theme":
      default:
        topFill = "var(--primary)";
        break;
    }
  }

  if (!bottomFill) {
    switch (variant) {
      case "green":
        bottomFill = "var(--foreground)";
        break;
      case "original":
        bottomFill = "#000000"; 
        break;
      case "monochrome":
        bottomFill = "currentColor";
        break;
      case "theme":
      default:
        bottomFill = "var(--foreground)";
        break;
    }
  }

  return (
    <div
      className={`relative inline-flex items-center justify-center shrink-0 ${glow ? "group" : ""} ${className}`}
      style={{ width: size, height: size }}
    >
      {/* Optional ambient theme glow */}
      {glow && (
        <div
          className="absolute inset-0 rounded-full blur-md opacity-40 transition-opacity duration-300 group-hover:opacity-75"
          style={{ background: topFill }}
        />
      )}

      <svg
        width={size}
        height={size}
        viewBox="0 0 200 240"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="relative z-10 transition-colors duration-300 drop-shadow-sm"
        style={style}
        {...props}
      >
        {/* Shield Outer Path Definition */}
        <defs>
          <clipPath id="msaj-shield-clip">
            <path d="M 100 8 C 145 10 185 24 190 32 L 190 132 C 190 184 100 232 100 232 C 100 232 10 184 10 132 L 10 32 C 15 24 55 10 100 8 Z" />
          </clipPath>
          <linearGradient id="msaj-green-grad" x1="100" y1="8" x2="100" y2="232" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--primary)" />
            <stop offset="100%" stopColor="var(--foreground)" />
          </linearGradient>
        </defs>

        <g clipPath="url(#msaj-shield-clip)">
          {/* Top Main Shield Body */}
          <path
            d="M 100 8 C 145 10 185 24 190 32 L 190 152 Q 100 115 10 152 L 10 32 C 15 24 55 10 100 8 Z"
            fill={topFill}
            className="transition-colors duration-300"
          />

          {/* Bottom Arch Pen Nib Base */}
          <path
            d="M 10 148 Q 100 112 190 148 L 190 132 C 190 184 100 232 100 232 C 100 232 10 184 10 132 Z"
            fill={bottomFill}
            className="transition-colors duration-300"
          />

          {/* Decorative Divider Arch Stroke */}
          <path
            d="M 10 148 Q 100 112 190 148"
            stroke={textColor}
            strokeWidth="3.5"
            fill="none"
            strokeLinecap="round"
          />

          {/* ── TOP SYMBOL: Flame ── */}
          <path
            d="M 100 24 C 103 33 109 40 109 47 C 109 56 102 61 96 57 C 93 55 91 50 93 45 C 93 45 87 50 87 58 C 87 68 94 72 100 72 C 108 72 115 65 115 54 C 115 42 105 32 100 24 Z"
            fill={textColor}
          />

          {/* ── TOP SYMBOL: Open Book ── */}
          {/* Left Page */}
          <path
            d="M 97 73 Q 60 55 24 76 Q 60 70 97 86 Z"
            fill={textColor}
          />
          {/* Right Page */}
          <path
            d="M 103 73 Q 140 55 176 76 Q 140 70 103 86 Z"
            fill={textColor}
          />
          {/* Book Spine Center */}
          <path
            d="M 97 84 Q 100 81 103 84 L 103 88 Q 100 86 97 88 Z"
            fill={textColor}
          />

          {/* ── MIDDLE SYMBOL: MSAJ Stylized Block Lettering ── */}
          {/* Letter M */}
          <path
            d="M 28 98 H 40 L 46 114 L 52 98 H 64 V 132 H 53 V 110 L 48 124 H 44 L 39 110 V 132 H 28 Z"
            fill={textColor}
          />
          {/* Letter S */}
          <path
            d="M 70 98 H 96 V 107 H 80 V 111 H 96 V 132 H 70 V 123 H 85 V 119 H 70 Z"
            fill={textColor}
          />
          {/* Letter A */}
          <path
            d="M 102 98 H 128 V 132 H 117 V 122 H 113 V 132 H 102 Z M 113 106 V 114 H 117 V 106 Z"
            fill={textColor}
          />
          {/* Letter J */}
          <path
            d="M 134 98 H 160 V 107 H 145 V 123 H 151 V 115 H 160 V 132 H 134 Z"
            fill={textColor}
          />

          {/* ── BOTTOM SYMBOL: Fountain Pen Nib ── */}
          {/* Pen Nib Body */}
          <path
            d="M 100 134 Q 120 134 126 155 L 118 206 C 114 216 100 226 100 226 C 100 226 86 216 82 206 L 74 155 Q 80 134 100 134 Z"
            fill={textColor}
          />
          {/* Pen Nib Inner Detail (Base Color Cutout) */}
          <path
            d="M 100 142 Q 114 142 118 157 L 112 200 C 109 208 100 216 100 216 C 100 216 91 208 88 200 L 82 157 Q 86 142 100 142 Z"
            fill={bottomFill}
          />
          {/* Pen Nib Breather Hole & Center Slit */}
          <circle cx="100" cy="180" r="4.5" fill={textColor} />
          <path
            d="M 98.5 180 L 98.5 218 L 101.5 218 L 101.5 180 Z"
            fill={textColor}
          />
        </g>

        {/* Outer Shield Crisp Border */}
        <path
          d="M 100 8 C 145 10 185 24 190 32 L 190 132 C 190 184 100 232 100 232 C 100 232 10 184 10 132 L 10 32 C 15 24 55 10 100 8 Z"
          stroke={textColor}
          strokeWidth="3.5"
          fill="none"
        />
      </svg>
    </div>
  );
};

export default MSAJLogo;
