// Shared runtime meta (snapshot + counts) fetched once from the API.
// StatusBar / home / About all read this so the dataset info is never
// duplicated or hardcoded (spec §24, UI-P0-1).
import { api } from '$lib/api/client';
import type { Meta } from '$lib/api/types';

export const metaState = $state<{
	meta: Meta | null;
	loading: boolean;
	error: string | null;
}>({
	meta: null,
	loading: false,
	error: null,
});

let started = false;

/** Fetch /api/meta exactly once per session; subsequent callers reuse it. */
export function ensureMeta(): void {
	if (started) return;
	started = true;
	metaState.loading = true;
	api
		.meta()
		.then((m) => (metaState.meta = m))
		.catch((e) => (metaState.error = e instanceof Error ? e.message : '加载失败'))
		.finally(() => (metaState.loading = false));
}
