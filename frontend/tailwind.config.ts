import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

// Fraud Forensics · dark forensic dashboard
// Brand: black/gray + #A44200 (deep burnt red)
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1rem", screens: { "2xl": "1400px" } },
    extend: {
      colors: {
        background: "#0A0A0A",
        surface: { DEFAULT: "#141414", elevated: "#1C1C1C" },
        foreground: "#F5F5F5",
        muted: { DEFAULT: "#1F1F1F", foreground: "#A3A3A3" },
        border: "#2A2A2A",
        input: "#2A2A2A",
        ring: "#A44200",
        primary: { DEFAULT: "#A44200", foreground: "#FFFFFF", hover: "#8B3800", muted: "#3A1900" },
        accent: { DEFAULT: "#A44200", foreground: "#FFFFFF" },
        card: { DEFAULT: "#141414", foreground: "#F5F5F5" },
        popover: { DEFAULT: "#1C1C1C", foreground: "#F5F5F5" },
        destructive: { DEFAULT: "#DC2626", foreground: "#FFFFFF" },
        success: "#22C55E",
        warning: "#F59E0B",
        scheme: {
          phantom_vendor: "#A44200",
          kickback: "#DC2626",
          round_tripping: "#D97706",
          threshold_splitting: "#CA8A04",
          revenue_inflation: "#B45309",
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
        "4xl": ["2.5rem", { lineHeight: "1.15", fontWeight: "700" }],
      },
      boxShadow: {
        sm: "0 1px 2px rgba(0,0,0,0.4)",
        DEFAULT: "0 4px 6px rgba(0,0,0,0.5)",
        lg: "0 10px 20px rgba(0,0,0,0.6)",
        xl: "0 20px 40px rgba(0,0,0,0.7)",
        glow: "0 0 20px rgba(164,66,0,0.35)",
      },
      borderRadius: { lg: "0.75rem", md: "0.5rem", sm: "0.375rem" },
      keyframes: {
        "fade-in": { "0%": { opacity: "0", transform: "translateY(4px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        "slide-in-left": { "0%": { opacity: "0", transform: "translateX(-16px)" }, "100%": { opacity: "1", transform: "translateX(0)" } },
        "pulse-glow": { "0%,100%": { boxShadow: "0 0 0 0 rgba(164,66,0,0.4)" }, "50%": { boxShadow: "0 0 0 12px rgba(164,66,0,0)" } },
      },
      animation: {
        "fade-in": "fade-in 200ms ease-out",
        "slide-in-left": "slide-in-left 240ms ease-out",
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
