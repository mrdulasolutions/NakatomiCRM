import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';
import { nakatomiDev } from './dev/nakatomi.mjs';

const withBackend = process.env.PUBLIC_NAKATOMI_DEV === 'true';

export default defineConfig({
  integrations: [react()],
  vite: {
    plugins: [tailwindcss(), ...(withBackend ? [nakatomiDev()] : [])],
    server: {
      strictPort: withBackend,
      fs: { deny: ['**/.env', '**/.env.*', '**/*.{crt,pem}', '**/.git/**', '**/.nakatomi-dev/**'] },
    },
  },
});
