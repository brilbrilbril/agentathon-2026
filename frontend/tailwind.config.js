/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        deloitte: {
          green: '#86BC25',
          dark: '#0F1214',
          slate: '#1B2228',
        },
      },
    },
  },
  plugins: [],
}
