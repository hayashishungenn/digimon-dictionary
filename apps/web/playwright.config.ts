import { defineConfig, devices } from '@playwright/test';

// E2E tests run against the real sync'd database + real FastAPI + the PRODUCTION
// web build (vite preview, no HMR — HMR reloads during dev can race with clicks).
export default defineConfig({
	testDir: './tests/e2e',
	fullyParallel: false,
	workers: 1, // serial: shared DB state + API server
	// a single retry absorbs cold-start/preview races against external image CDNs
	retries: 1,
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
			command: 'uv run uvicorn apps.api.main:app --port 8000',
			cwd: '../..',
			url: 'http://localhost:8000/api/health',
			reuseExistingServer: !process.env.CI,
			timeout: 60_000,
		},
		{
			command: 'npm run build && npm run preview -- --port 4173',
			url: 'http://localhost:4173',
			reuseExistingServer: !process.env.CI,
			timeout: 120_000,
		},
	],
});
