/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,js,ts}"],
  theme: {
    extend: {
      colors: {
        magi: {
          bg: "#060606",
          panel: "#101010",
          line: "#303030",
          neon: "#f4f4f5",
          warn: "#d4d4d8",
          danger: "#a1a1aa",
          success: "#e4e4e7",
          idle: "#d4d4d8"
        }
      },
      boxShadow: {
        neon: "0 0 0 1px rgba(244,244,245,.22)"
      }
    }
  },
  plugins: []
};
