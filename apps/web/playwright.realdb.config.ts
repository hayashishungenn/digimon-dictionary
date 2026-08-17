import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Real-DB E2E profile (P1-3): runs against data/digidex.sqlite, NOT the
// hermetic fixture. Requires a synced DB; the spec skips when it is absent.
const REAL_DB = path.resolve(__dirname, '../../data/digidex.sqlite');

export default defineConfig({
	testDir: './tests/e2e-realdb',
	fullyParallel: false,
	workers: 1, // serial: shared real DB + one API server
	reporter: [['list']],
	timeout: 90_000,
	use: {
		baseURL: 'http://localhost:4174',
		trace: 'on-first-retry',
	},
	projects: [
		{ name: 'realdb-desktop', use: { ...devices['Desktop Chrome'] } },
		{ name: 'realdb-mobile', use: { ...devices['Pixel 7'] } }, // narrow-screen
	],
	webServer: [
		{
			// the real DB is served read-only; never rebuilt here
			command:
				'uv run python -m uvicorn apps.api.main:app --port 8010',
			cwd: '../..',
			env: {
				...process.env,
				DIGIDEX_DB: REAL_DB,
				DIGIDEX_CORS_ORIGINS: 'http://localhost:4174',
			},
			url: 'http://localhost:8010/api/health',
			reuseExistingServer: false,
			timeout: 60_000,
		},
		{
			// production build pointed at the realdb API, served via preview
			command: 'npm run build && npm run preview -- --port 4174',
			cwd: '.',
			env: { ...process.env, VITE_API_BASE: 'http://localhost:8010/api' },
			url: 'http://localhost:4174',
			reuseExistingServer: false,
			timeout: 180_000,
		},
	],
});
