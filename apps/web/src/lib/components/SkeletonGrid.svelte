<script lang="ts">
	// Skeleton loading placeholder: low-contrast shimmer blocks that stabilize
	// the layout instead of a bare spinner (UI-P1-1). Renders N card skeletons.
	interface Props {
		count?: number;
	}
	let { count = 8 }: Props = $props();
</script>

<div class="skeleton-grid" aria-label="加载中" aria-busy="true" role="status">
	{#each Array(count) as _, i}
		<div class="sk-card" style:animation-delay={`${(i % 6) * 90}ms`}>
			<div class="sk-thumb"></div>
			<div class="sk-line w70"></div>
			<div class="sk-line w40"></div>
			<div class="sk-line w55"></div>
		</div>
	{/each}
</div>

<style>
	.skeleton-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
		gap: 14px;
	}
	.sk-card {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		padding: 10px;
	}
	.sk-thumb {
		aspect-ratio: 1;
		border-radius: calc(var(--radius-sm) - 2px);
		background: var(--surface-2);
		margin-bottom: 10px;
		opacity: 0.5;
		animation: digidex-shimmer 1.4s var(--ease) infinite alternate;
	}
	.sk-line {
		height: 10px;
		border-radius: 4px;
		background: var(--surface-2);
		margin-top: 8px;
		opacity: 0.5;
		animation: digidex-shimmer 1.4s var(--ease) infinite alternate;
	}
	.w70 { width: 70%; }
	.w40 { width: 40%; }
	.w55 { width: 55%; }

	@keyframes digidex-shimmer {
		from { opacity: 0.35; }
		to { opacity: 0.7; }
	}
	@media (prefers-reduced-motion: reduce) {
		.sk-thumb, .sk-line { animation: none; }
	}
</style>
