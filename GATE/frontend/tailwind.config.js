/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,js,ts}"],
  theme: {
    extend: {
      colors: {
        magi: {
          bg: "#070b14",
          panel: "#0e1629",
          line: "#1d3257",
          neon: "#5dd6ff",
          warn: "#ffd86b",
          danger: "#ff6f91",
          success: "#70f4a5",
          idle: "#8cb5ff"
        }
      },
      boxShadow: {
        neon: "0 0 0 1px rgba(93,214,255,.22), 0 0 28px rgba(93,214,255,.16)"
      }
    }
  },
  plugins: []
};
