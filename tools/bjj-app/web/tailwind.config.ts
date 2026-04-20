import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{html,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // Category chip colours — match the approved mockup
        cat: {
          standing: '#b7bcc7',
          'guard-top': '#f0c958',
          'guard-bottom': '#7ba9e6',
          'dominant-top': '#7fc98d',
          'inferior-bottom': '#d89090',
          'leg-ent': '#f0965c',
          scramble: '#b083d8',
          pass: '#e6c47e',
          sub: '#8bd6a1'
        },
        player: {
          greig: '#f2f2f2',
          anthony: '#e36a6a'
        }
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'SF Pro Display',
          'Segoe UI',
          'system-ui',
          'sans-serif'
        ]
      }
    }
  },
  plugins: []
} satisfies Config;
