import { describe, it, expect, beforeEach, vi } from 'vitest';

// The meta store (shared by StatusBar / home / About) must fetch /api/meta
// exactly once per session and expose loading/error state (UI-P0-1).
const META = {
	snapshot: { snapshot_date: '2026-08-15', official_count: 6, extended_count: 0, total_count: 6 },
	counts: { total: 6, official: 6, extended: 0 },
	levels: [],
	attributes: [],
	types: [],
	fields: [],
	groups: []
};

vi.mock('$lib/api/client', () => {
	class ApiError extends Error {
		constructor(public status: number, message: string) {
			super(message);
			this.name = 'ApiError';
		}
	}
	return {
		api: {
			meta: vi.fn()
		},
		ApiError
	};
});

async function loadStore() {
	vi.resetModules();
	return await import('$lib/stores/meta.svelte');
}

describe('meta store (shared dataset status)', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('fetches meta once and caches it for later callers', async () => {
		const client = await import('$lib/api/client');
		(client.api.meta as ReturnType<typeof vi.fn>).mockResolvedValue(META);

		const store = await loadStore();
		store.ensureMeta();
		store.ensureMeta(); // second call must not re-fetch

		// wait for the async fetch to settle
		await vi.waitFor(() => expect(store.metaState.loading).toBe(false));
		expect(client.api.meta).toHaveBeenCalledTimes(1);
		expect(store.metaState.meta?.counts.total).toBe(6);
		expect(store.metaState.error).toBeNull();
	});

	it('surfaces a load error instead of crashing', async () => {
		const client = await import('$lib/api/client');
		(client.api.meta as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('down'));

		const store = await loadStore();
		store.ensureMeta();
		await vi.waitFor(() => expect(store.metaState.loading).toBe(false));
		expect(store.metaState.error).toBe('down');
		expect(store.metaState.meta).toBeNull();
		expect(store.metaState.dbUnavailable).toBe(false);
	});

	it('marks dbUnavailable on a 503 (DB not synced)', async () => {
		const client = await import('$lib/api/client');
		const { ApiError } = client;
		(client.api.meta as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(503, 'Dataset not synced yet'));

		const store = await loadStore();
		store.ensureMeta();
		await vi.waitFor(() => expect(store.metaState.loading).toBe(false));
		expect(store.metaState.dbUnavailable).toBe(true);
	});

	it('ensureMeta(true) re-fetches after a failure (retry works)', async () => {
		const client = await import('$lib/api/client');
		const meta = client.api.meta as ReturnType<typeof vi.fn>;
		meta.mockRejectedValueOnce(new Error('down')).mockResolvedValueOnce(META);

		const store = await loadStore();
		store.ensureMeta(); // first attempt fails
		await vi.waitFor(() => expect(store.metaState.error).toBe('down'));
		store.ensureMeta(true); // retry must actually re-fetch
		await vi.waitFor(() => expect(store.metaState.meta?.counts.total).toBe(6));
		expect(meta).toHaveBeenCalledTimes(2);
		expect(store.metaState.error).toBeNull();
	});
});
