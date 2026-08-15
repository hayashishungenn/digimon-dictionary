<script lang="ts">
	// Reusable empty state: explicit 'no data' that never fabricates content,
	// with an optional action back to the index (UI-P1-1).
	interface Props {
		title?: string;
		message?: string;
		ctaLabel?: string;
		ctaHref?: string;
	}
	let { title = '没有找到匹配的内容', message, ctaLabel, ctaHref = '/' }: Props = $props();
</script>

<div class="empty-state">
	<span class="empty-mark" aria-hidden="true">◌</span>
	<p class="empty-title">{title}</p>
	{#if message}<p class="empty-message">{message}</p>{/if}
	{#if ctaLabel}
		<a class="btn btn-primary" href={ctaHref}>{ctaLabel}</a>
	{/if}
</div>

<style>
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 6px;
		min-height: 180px;
		text-align: center;
		color: var(--text-faint);
		border: 1px dashed var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		padding: 24px;
		margin: 8px 0;
	}
	.empty-mark {
		font-size: 34px;
		line-height: 1;
		color: var(--border-strong);
	}
	.empty-title {
		margin: 4px 0 0;
		font-size: 14px;
		font-weight: 600;
		color: var(--text-dim);
	}
	.empty-message {
		margin: 0 0 8px;
		font-size: 12.5px;
		color: var(--text-faint);
	}
</style>
