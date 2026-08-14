import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Deterministic hermetic fixture: E2E never touches data/digidex.sqlite or the
// network. The API webServer builds it first (T6.7).
const FIXTURE_DB = path.resolve(__dirname, 'tests/fixtures/e2e.sqlite');

// E2E tests run against a hermetic fixture DB + the real FastAPI + the PRODUCTION
// web build (vite preview, no HMR — HMR reloads during dev can race with clicks).
export default defineConfig({
	testDir: './tests/e2e',
	fullyParallel: false,
	workers: 1, // serial: shared DB state + API server
	reporter: [['list'], ['html', { open: 'never' }]],
	use: {
		baseURL: 'http://localhost:4173',
		trace: 'on-first-retry',
	},
	projects: [
		{ name: 'chromium', use: { ...devices['Desktop Chrome'] } },
	],
	webServer: [
		{
			// build the hermetic fixture, then serve it via the API
			command:
				'uv run python apps/web/tests/fixtures/build_e2e_fixture.py && uv run uvicorn apps.api.main:app --port 8000',
			cwd: '../..',
			env: { ...process.env, DIGIDEX_DB: FIXTURE_DB },
			url: 'http://localhost:8000/api/health',
			reuseExistingServer: false,
			timeout: 60_000,
		},
		{
			command: 'npm run build && npm run preview -- --port 4173',
			url: 'http://localhost:4173',
			reuseExistingServer: false,
			timeout: 120_000,
		},
	],
});
