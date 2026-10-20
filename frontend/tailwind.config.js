/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f8f6f1",
        ink: "#20221f",
        coral: "#e4794c",
        olive: "#5e705c",
        line: "#e6e1d9",
      },
      fontFamily: {
        sans: ["DM Sans", "sans-serif"],
        serif: ["Newsreader", "serif"],
        mono: ["DM Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
