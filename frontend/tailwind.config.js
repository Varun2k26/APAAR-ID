/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Institutional blue (single accent) and a cool neutral scale.
        brand: { 50: "#eef3fa", 100: "#d9e4f2", 200: "#b3c8e4", 300: "#7fa1cf", 400: "#4b78b5", 500: "#2a5c9e",
                 600: "#1b4b8a", 700: "#0f3e7a", 800: "#0c3164", 900: "#0a2650" },
        ink: { 50: "#f6f7f9", 100: "#eceef1", 200: "#dcdfe4", 300: "#c3c8cf", 400: "#8d95a0", 500: "#5f6873",
               600: "#47505b", 700: "#343b44", 800: "#22272e", 900: "#14181d" },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: { DEFAULT: "4px", sm: "2px", md: "6px" },
      fontSize: { "2xs": ["11px", "16px"] },
    },
  },
  plugins: [],
};
