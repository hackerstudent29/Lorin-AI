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
          "inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 disabled:pointer-events-none disabled:opacity-50 active:scale-95 cursor-pointer",
          {
            "bg-gradient-to-r from-emerald-600 to-green-700 text-white hover:opacity-90 shadow-md shadow-emerald-600/20": variant === "default",
            "border border-slate-200 bg-white text-slate-800 hover:bg-emerald-50 hover:text-emerald-700 hover:border-emerald-300": variant === "outline",
            "hover:bg-emerald-50 text-slate-600 hover:text-emerald-700": variant === "ghost",
            "bg-emerald-100 text-emerald-900 hover:bg-emerald-200": variant === "secondary",
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
