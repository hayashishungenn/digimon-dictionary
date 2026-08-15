<script lang="ts">
	// Reusable error banner that never exposes SQL/paths/stack details, and
	// offers a retry + a way back home (UI-P1-1).
	interface Props {
		message: string;
		detail?: string | null; // optional user-safe hint (never raw errors)
		retry?: () => void;
	}
	let { message, detail, retry }: Props = $props();
</script>

<div class="error-state" role="alert">
	<p class="err-title">{message}</p>
	{#if detail}<p class="err-detail">{detail}</p>{/if}
	<div class="err-actions">
		{#if retry}
			<button class="btn" onclick={retry}>重试</button>
		{/if}
		<a class="btn" href="/">返回首页</a>
	</div>
</div>

<style>
	.error-state {
		background: rgba(255, 93, 115, 0.07);
		border: 1px solid rgba(255, 93, 115, 0.4);
		border-radius: var(--radius);
		padding: 18px 20px;
		margin: 16px 0;
	}
	.err-title {
		margin: 0 0 4px;
		color: var(--danger);
		font-weight: 700;
		font-size: 14px;
	}
	.err-detail {
		margin: 0 0 12px;
		color: var(--text-dim);
		font-size: 12.5px;
		line-height: 1.5;
	}
	.err-actions {
		display: flex;
		gap: 8px;
	}
</style>
