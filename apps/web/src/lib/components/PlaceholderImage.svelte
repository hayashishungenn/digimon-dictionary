<script lang="ts">
	// Graceful image with unified placeholder fallback (spec §27).
	// The placeholder sits behind the image; the image fades in on load and is
	// replaced by the placeholder on error — never a broken-image icon.
	interface Props {
		src: string | null | undefined;
		alt: string;
		label?: string;
		loading?: 'lazy' | 'eager';
	}
	let { src, alt, label, loading = 'lazy' }: Props = $props();
	let failed = $state(false);
	let loaded = $state(false);

	// reset state when the source changes (cards are reused across items)
	$effect(() => {
		void src;
		failed = false;
		loaded = false;
	});

	function onError() {
		failed = true;
	}
</script>

<span class="img-wrap">
	{#if src && !failed}
		<img
			{src}
			{alt}
			{loading}
			decoding="async"
			onerror={onError}
			onload={() => (loaded = true)}
			class:img-visible={loaded}
		/>
	{/if}
	{#if failed || !src}
		<span class="img-placeholder" role="img" aria-label={alt}>
			{label ?? 'NO IMAGE'}
		</span>
	{/if}
</span>

<style>
	.img-wrap {
		display: grid;
		place-items: center;
		width: 100%;
		height: 100%;
		position: relative;
	}
	.img-wrap :global(img) {
		width: 82%;
		height: 82%;
		object-fit: contain;
		image-rendering: pixelated;
		position: absolute;
		opacity: 0;
		transition: opacity 0.2s;
	}
	.img-wrap :global(img.img-visible) {
		opacity: 1;
	}
</style>
