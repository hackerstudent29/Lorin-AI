import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost" | "secondary"
  size?: "default" | "sm" | "lg" | "icon"
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return (
      <button
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 disabled:pointer-events-none disabled:opacity-50 active:scale-95 cursor-pointer",
          {
            "bg-gradient-to-r from-emerald-500 to-teal-600 text-white hover:opacity-90 shadow-md shadow-emerald-500/20": variant === "default",
            "border border-slate-800 bg-slate-900/80 text-slate-200 hover:bg-slate-800 hover:text-white": variant === "outline",
            "hover:bg-slate-800/60 text-slate-400 hover:text-slate-200": variant === "ghost",
            "bg-slate-800 text-slate-200 hover:bg-slate-700": variant === "secondary",
          },
          {
            "h-10 px-4 py-2": size === "default",
            "h-8 rounded-lg px-3 text-xs": size === "sm",
            "h-12 rounded-2xl px-6 text-base": size === "lg",
            "size-10 rounded-xl p-0": size === "icon",
          },
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button }
