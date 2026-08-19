import React from "react";
import { Bot } from "lucide-react";

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
 * MSAJCE Bot Logo Component
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

      <div 
        className="relative z-10 flex items-center justify-center rounded-xl transition-colors duration-300 drop-shadow-sm"
        style={{ 
          background: topFill, 
          width: '100%', 
          height: '100%',
          ...style
        }}
      >
        <Bot 
          size={typeof size === 'number' ? size * 0.6 : '60%'} 
          color={textColor} 
          strokeWidth={2}
          {...(props as any)} 
        />
      </div>
    </div>
  );
};

export default MSAJLogo;
