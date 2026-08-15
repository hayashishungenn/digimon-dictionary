<script lang="ts">
	// Terminal-style section header: mono code + title, with an optional
	// right-aligned aside (e.g. a count). Keeps section headings visually
	// consistent across pages (UI-P0-1).
	interface Props {
		title: string;
		code?: string;
		aside?: string;
	}
	let { title, code, aside }: Props = $props();
</script>

<h2 class="section-header">
	<span class="sh-title">
		{#if code}<span class="sh-code mono">{code}</span>{/if}
		{title}
	</span>
	{#if aside}<span class="sh-aside mono">{aside}</span>{/if}
</h2>
