/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      colors: {
        surface: "#fcfcfb",
        panel: "#ffffff",
        ink: { DEFAULT: "#0b0b0b", 2: "#52514e", 3: "#7a7974" },
        line: "#e4e3df",
        brand: { 50: "#eef5fd", 100: "#cde2fb", 500: "#256abf", 600: "#1c5cab", 700: "#184f95", 900: "#0d366b" },
        good: "#0ca30c",
        warning: "#fab219",
        serious: "#ec835a",
        critical: "#d03b3b",
      },
    },
  },
  plugins: [],
};
