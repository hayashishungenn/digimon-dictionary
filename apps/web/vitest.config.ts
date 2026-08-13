import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const rootDir = import.meta.dirname;

export default defineConfig({
	plugins: [svelte()],
	resolve: {
		alias: {
			$lib: `${rootDir}/src/lib`
		}
	},
	test: {
		environment: 'jsdom',
		include: ['tests/unit/**/*.test.ts'],
		globals: true
	}
});
