import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

// Unit tests cover pure TypeScript modules only. This file is separate from vite.config.ts on purpose:
// it does not load the Tailwind plugin or the dev-server API proxy. The `@` alias matches vite.config.ts.
export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
