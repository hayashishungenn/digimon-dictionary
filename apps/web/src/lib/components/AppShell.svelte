<script lang="ts">
	// Application shell: skip link, header (logo + primary nav), data status bar,
	// page content slot, and a minimal footer. One step back to home or search
	// from anywhere (UI-P0-1).
	import favicon from '$lib/assets/favicon.svg';
	import StatusBar from './StatusBar.svelte';

	interface Props {
		children: import('svelte').Snippet;
	}
	let { children }: Props = $props();
</script>

<a class="skip-link" href="#main">跳到主要内容</a>

<header class="topbar">
	<div class="topbar-inner">
		<a href="/" class="logo" aria-label="DigiDex 首页">
			<span class="logo-mark" aria-hidden="true"><img src={favicon} alt="" width="26" height="26" /></span>
			<span class="logo-text">DigiDex</span>
			<span class="logo-sub">数码宝贝全图鉴</span>
		</a>
		<nav class="nav-links" aria-label="主导航">
			<a href="/">图鉴</a>
			<a href="/favorites">收藏</a>
			<a href="/review">复核队列</a>
			<a href="/about">关于 / 数据</a>
		</nav>
	</div>
</header>

<StatusBar />

<main id="main" class="shell">
	{@render children()}
</main>

<footer class="site-footer">
	<div class="footer-inner">
		<span class="mono">DIGIDEX</span>
		<span>个人本地图鉴 · 数据快照与总数由运行时计算，不硬编码</span>
		<span class="faint">本项目不隶属于 Bandai / Bandai Namco</span>
	</div>
</footer>
