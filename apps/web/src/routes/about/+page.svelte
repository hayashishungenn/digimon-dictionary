<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import type { Meta } from '$lib/api/types';

	let meta = $state<Meta | null>(null);
	let error = $state<string | null>(null);

	onMount(() => {
		api.meta().then((m) => (meta = m)).catch((e) => (error = e instanceof Error ? e.message : '加载失败'));
	});
</script>

<svelte:head>
	<title>关于 · DigiDex</title>
</svelte:head>

<h1 class="page-title">关于 DigiDex</h1>
<p>
	DigiDex 是一个数码宝贝/数码兽全图鉴 Canonical Knowledge Base：三语言名称（简体中文 / English / 日本語）、
	等级、属性、类型、适应领域、所属组织、技能、进化关系（有向多对多图）、简介与首次登场等资料。
</p>
<p class="dim">
	本项目不隶属于 Bandai / Bandai Namco。数码宝贝相关的角色、名称与美术版权归其相应权利方所有，
	仅用于个人研究、收藏与查询。
</p>

<div class="section-title">数据集快照 Dataset Snapshot</div>
{#if error}
	<div class="error-box">{error}</div>
{:else if meta}
	<div class="stat-grid">
		<div class="stat-cell"><div class="stat-v">{meta.counts.official.toLocaleString()}</div><div class="stat-k">官方图鉴 Official</div></div>
		<div class="stat-cell"><div class="stat-v">{meta.counts.extended.toLocaleString()}</div><div class="stat-k">扩展图鉴 Extended</div></div>
		<div class="stat-cell"><div class="stat-v">{meta.counts.total.toLocaleString()}</div><div class="stat-k">总计 Total</div></div>
		<div class="stat-cell">
			<div class="stat-v mono">{meta.snapshot?.snapshot_date ?? '—'}</div>
			<div class="stat-k">数据快照日期</div>
		</div>
	</div>
{:else}
	<div class="spinner"></div>
{/if}

<p class="faint" style="font-size:12px">
	数量由运行时从数据库计算得出，随 sync-data 更新而更新。
</p>

<div class="section-title">数据来源 Sources</div>
<ul class="source-list">
	<li><a href="https://digimon.net/reference_zh-CHS/" target="_blank" rel="noopener">Digimon Official Reference Book</a> — 官方状态、官方名称</li>
	<li><a href="https://wikimon.net/" target="_blank" rel="noopener">Wikimon</a> — 实体枚举、扩展集、简介、进化</li>
	<li><a href="https://digi-api.com/" target="_blank" rel="noopener">Digi-API</a> — 结构化元数据、图片、技能、进化</li>
	<li><a href="https://digimons.net/digimon/" target="_blank" rel="noopener">digimons.net</a> — 简体中文社区通用译名</li>
	<li><a href="https://digidb.io/" target="_blank" rel="noopener">digidb.io</a> — 游戏数值（独立于世界观）</li>
</ul>

<div class="section-title">技术栈</div>
<ul class="source-list">
	<li>数据管线：Python 3.14 · httpx · SQLite（FTS5）</li>
	<li>API：FastAPI · uvicorn</li>
	<li>Web：TypeScript · SvelteKit</li>
	<li>测试：pytest · Vitest · Playwright</li>
</ul>

<style>
	.page-title {
		margin-top: 24px;
		font-size: 26px;
	}
	.stat-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 12px;
	}
	.stat-cell {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 16px;
		text-align: center;
	}
	.stat-v {
		font-size: 26px;
		font-weight: 800;
		color: var(--accent);
	}
	.stat-k {
		font-size: 12px;
		color: var(--text-faint);
		margin-top: 2px;
	}
	.source-list {
		line-height: 1.9;
		color: var(--text-dim);
	}
</style>
