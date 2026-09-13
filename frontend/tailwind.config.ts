import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        // Design System — persisted in design-system/claudius-maximus-forensic-auditor/MASTER.md
        primary: { DEFAULT: "#1E40AF", foreground: "#FFFFFF" },
        secondary: { DEFAULT: "#3B82F6", foreground: "#FFFFFF" },
        accent: { DEFAULT: "#D97706", foreground: "#FFFFFF" },
        background: "#F8FAFC",
        foreground: "#1E3A8A",
        muted: { DEFAULT: "#E9EEF6", foreground: "#475569" },
        border: "#DBEAFE",
        input: "#DBEAFE",
        ring: "#1E40AF",
        destructive: { DEFAULT: "#DC2626", foreground: "#FFFFFF" },
        card: { DEFAULT: "#FFFFFF", foreground: "#1E3A8A" },
        popover: { DEFAULT: "#FFFFFF", foreground: "#1E3A8A" },
        success: "#059669",
        warning: "#D97706",
        // Scheme-type accents (WCAG AA sobre fondo #F8FAFC)
        scheme: {
          phantom_vendor: "#6366F1",
          kickback: "#E11D48",
          round_tripping: "#0891B2",
          threshold_splitting: "#EA580C",
          revenue_inflation: "#059669",
        },
      },
      fontFamily: {
        sans: ["Fira Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Fira Code", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1.5" }],
        sm: ["0.8125rem", { lineHeight: "1.55" }],
        base: ["0.875rem", { lineHeight: "1.55" }],
        lg: ["1rem", { lineHeight: "1.5" }],
        xl: ["1.125rem", { lineHeight: "1.4" }],
        "2xl": ["1.5rem", { lineHeight: "1.3", fontWeight: "600" }],
        "3xl": ["2rem", { lineHeight: "1.2", fontWeight: "600" }],
      },
      spacing: {
        xs: "0.125rem",
        sm: "0.25rem",
        md: "0.5rem",
        lg: "0.75rem",
        xl: "1rem",
        "2xl": "1.5rem",
        "3xl": "2rem",
      },
      boxShadow: {
        sm: "0 1px 2px rgba(0,0,0,0.05)",
        DEFAULT: "0 4px 6px rgba(0,0,0,0.1)",
        lg: "0 10px 15px rgba(0,0,0,0.1)",
        xl: "0 20px 25px rgba(0,0,0,0.15)",
      },
      borderRadius: {
        lg: "0.75rem",
        md: "0.5rem",
        sm: "0.375rem",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-left": {
          "0%": { opacity: "0", transform: "translateX(-16px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 200ms ease-out",
        "slide-in-left": "slide-in-left 240ms ease-out",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
