<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import AppShell from '$lib/components/AppShell.svelte';

	let { children } = $props();
</script>

<svelte:head>
	<title>DigiDex · 数码宝贝全图鉴</title>
	<meta name="description" content="数码宝贝/数码兽全图鉴 — 三语言（简体中文/English/日本語）canonical 知识库" />
	<link rel="icon" href={favicon} />
</svelte:head>

<AppShell>{@render children()}</AppShell>
