<script lang="ts">
	// Data status bar: runtime snapshot date + official/extended/total from the
	// API (never hardcoded). Also surfaces DB-unavailable / load errors, which
	// every page benefits from without duplicating the fetch (UI-P0-1).
	import { ensureMeta, metaState } from '$lib/stores/meta.svelte';
	import { onMount } from 'svelte';

	onMount(() => ensureMeta());
</script>

<div class="statusbar" role="status" aria-live="polite">
	<div class="statusbar-inner">
		{#if metaState.error}
			<span class="st st-error">数据服务不可用（请确认已运行后端并已 sync-data）</span>
		{:else if metaState.meta}
			<span class="st mono">
				SNAPSHOT <span class="st-strong">{metaState.meta.snapshot?.snapshot_date ?? '—'}</span>
			</span>
			<span class="st mono">
				<span class="st-strong">{metaState.meta.counts.total.toLocaleString()}</span> TOTAL ·
				<span class="st-ok">{metaState.meta.counts.official.toLocaleString()}</span> 官方 ·
				<span class="st-ext">{metaState.meta.counts.extended.toLocaleString()}</span> 扩展
			</span>
		{:else}
			<span class="st mono">读取数据集状态…</span>
		{/if}
	</div>
</div>
