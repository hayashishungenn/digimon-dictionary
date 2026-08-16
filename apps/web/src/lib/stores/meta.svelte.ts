// Shared runtime meta (snapshot + counts) fetched once from the API.
// StatusBar / home / About all read this so the dataset info is never
// duplicated or hardcoded (spec §24, UI-P0-1).
import { api, ApiError } from '$lib/api/client';
import type { Meta } from '$lib/api/types';

export const metaState = $state<{
	meta: Meta | null;
	loading: boolean;
	error: string | null;
	dbUnavailable: boolean;
}>({
	meta: null,
	loading: false,
	error: null,
	dbUnavailable: false,
});

let started = false;

/** Fetch /api/meta exactly once per session; subsequent callers reuse it.
 *  Pass `force=true` (e.g. a retry button) to re-fetch after a failure. */
export function ensureMeta(force = false): void {
	if (started && !force) return;
	started = true;
	metaState.loading = true;
	api
		.meta()
		.then((m) => {
			metaState.meta = m;
			metaState.error = null;
			metaState.dbUnavailable = false;
		})
		.catch((e) => {
			// A 503 means the DB isn't synced yet; other failures are network/server.
			metaState.dbUnavailable = e instanceof ApiError && e.status === 503;
			metaState.error = e instanceof Error ? e.message : '加载失败';
		})
		.finally(() => (metaState.loading = false));
}
