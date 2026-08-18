---
name: msajce-design
description: Design system rules and guidelines for MSAJCE website, ensuring an Apple-inspired premium aesthetic with precise spacing and polished UI, while strictly using MSAJCE colors and fonts.
---

# MSAJCE Premium Design System Guidelines

## Brand & Foundations

*   **Design Aesthetic**: Bold, minimalist grid structure, strong margins, and large, editorial type hierarchy (UAL style) fused with Apple-like smooth transitions, blur effects (backdrop-filter), and clean layouts.
*   **Spacing Scale**: Use precise spacing: `4/8/12/16/24/32/48/64/96`.

### Typography
**Do NOT change these fonts.**
*   **Primary Typeface**: `Switzer` (Neo-Grotesque, highly clean and modern, used for all headings, body, and UI elements).

### Color Palette & Theming
**Do NOT change these colors.** Use ONLY these five colors for the entire site:
*   **Primary Blue**: `#005DA6`
*   **White**: `#FFFFFF`
*   **Dark Gray 1**: `#616161`
*   **Dark Gray 2**: `#595959`
*   **Black**: `#000000`

**Theme Toggle Rule (Light & Dark Theme)**:
*   **Rule**: Every page, component, or layout added or modified must support both Light and Dark themes.
*   **Default State**: The website defaults to **light mode**

## Implementation in this project

*   **Tokens live in `src/styles.css`**: `:root` holds the light theme, `.dark` the dark theme. Both define `--primary-blue`, `--bg-color`, `--text-color`, `--card-bg`, `--border-color` plus the shadcn semantic tokens.
*   **Never hardcode** `text-white`, `bg-black`, or hex colors in components. Use `bg-background`, `text-foreground`, `text-muted-foreground`, `border-border`, `bg-primary`/`text-primary-foreground`, or opacity variants like `text-foreground/60`.
*   **Theme toggle**: `src/components/ThemeToggle.tsx` toggles the `dark` class on `<html>` and persists to `localStorage['msajce-theme']`. An inline script in `src/routes/__root.tsx` applies it before paint to avoid flashing.
*   **Dark theme accents**: on black, `--primary-blue` and `--primary` resolve to white (palette-safe) instead of `#005DA6`, which lacks contrast on black.
*   **Logo**: rendered via the asset pointer `src/assets/msajce-logo.png.asset.json` with `dark:brightness-0 dark:invert` so it reads on both themes.
*   **Type**: Switzer is loaded from Fontshare in the root route head and mapped to `--font-sans` / `--font-display`.
