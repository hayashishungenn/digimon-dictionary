<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';

	let { children } = $props();
</script>

<svelte:head>
	<title>DigiDex · 数码宝贝全图鉴</title>
	<meta name="description" content="数码宝贝/数码兽全图鉴 — 三语言（简体中文/English/日本語）canonical 知识库" />
	<link rel="icon" href={favicon} />
</svelte:head>

<header class="site-header">
	<div class="site-header-inner">
		<a href="/" class="logo" aria-label="DigiDex 首页">
			<span class="logo-glyph">◢</span>
			<span>DigiDex</span>
			<span class="logo-sub">数码宝贝全图鉴</span>
		</a>
		<nav class="nav-links" aria-label="主导航">
			<a href="/">图鉴</a>
			<a href="/about">关于</a>
		</nav>
	</div>
</header>

<main class="shell">
	{@render children()}
</main>
