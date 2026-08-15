<script lang="ts">
	import { api } from '$lib/api/client';
	import type { DigimonDetail } from '$lib/api/types';
	import PlaceholderImage from '$lib/components/PlaceholderImage.svelte';
	import Badges, { levelLabel, attrLabel } from '$lib/components/Badges.svelte';
	import EvolutionGraph from '$lib/components/EvolutionGraph.svelte';
	import { isFavorite, toggleFavorite } from '$lib/stores/favorites.svelte';

	let { params } = $props();
	let slug = $derived(params.slug);

	let data = $state<DigimonDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let evoDepth = $state(1);
	let evoLoading = $state(false);
	let evoError = $state<string | null>(null);
	const MAX_EVO_DEPTH = 3;

	// Request sequence token: when the route slug changes quickly, only the
	// newest detail response may win (T6.1 / T6.3).
	let reqSeq = 0;

	async function load() {
		const my = ++reqSeq;
		loading = true;
		error = null;
		try {
			const d = await api.detail(slug);
			if (my !== reqSeq) return; // stale detail — drop it
			data = d;
			evoDepth = 1;
			evoError = null;
		} catch (e) {
			if (my !== reqSeq) return;
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			if (my === reqSeq) loading = false;
		}
	}

	async function expandEvo() {
		const cur = data;
		if (!cur || evoLoading || evoDepth >= MAX_EVO_DEPTH) return;
		evoLoading = true;
		evoError = null;
		const next = evoDepth + 1;
		try {
			const g = await api.evolution(slug, next);
			evoDepth = next;
			data = { ...cur, evolution: g };
		} catch (e) {
			// keep current depth on failure, surface the error so the user can retry
			evoError = e instanceof Error ? e.message : '进化图加载失败';
		} finally {
			evoLoading = false;
		}
	}

	// collapse back to a shallower depth when the graph was truncated or too large
	async function setDepth(next: number) {
		const cur = data;
		if (!cur || evoLoading || next < 1 || next >= evoDepth) return;
		evoLoading = true;
		evoError = null;
		try {
			const g = await api.evolution(slug, next);
			evoDepth = next;
			data = { ...cur, evolution: g };
		} catch (e) {
			evoError = e instanceof Error ? e.message : '进化图加载失败';
		} finally {
			evoLoading = false;
		}
	}

	// Reload whenever the route slug changes (SvelteKit reuses the component).
	$effect(() => {
		load();
	});

	function relTypeLabel(t: string) {
		const map: Record<string, string> = {
			variant: '变体',
			x_antibody: 'X抗体形态',
			mode_change: '模式变化',
			black_variant: '黑色变体',
			same_species: '同种族',
			fusion_component: '合体组件',
			counterpart: '对应形态',
			related: '相关'
		};
		return map[t] ?? t;
	}

	// Image status derived from the digimon_image rows (P0-3): the UI expresses
	// downloaded / remote-only / failed / missing instead of silently hiding it.
	let imageStatus = $derived.by(() => {
		if (!data) return null;
		const main = data.images.find((i) => i.image_type === 'main_image');
		if (!main) return { kind: 'missing', text: '图片缺失（无来源）' };
		if (main.download_status === 'downloaded') return { kind: 'downloaded', text: '图片已本地缓存' };
		if (main.download_status === 'failed') return { kind: 'failed', text: `图片下载失败${main.failure_reason ? `：${main.failure_reason}` : ''}` };
		if (main.download_status === 'pending') return { kind: 'pending', text: '图片待下载' };
		return { kind: main.download_status, text: `图片状态：${main.download_status}` };
	});

	// Fields with a recorded cross-source conflict, for the source table (P1-2).
	let conflictFields = $derived.by(() => new Set((data?.conflicts ?? []).map((c) => c.field)));
	function fieldStatus(field: string): { kind: string; label: string } {
		if (conflictFields.has(field)) return { kind: 'conflict', label: '冲突' };
		const p = data?.source.find((s) => s.field === field);
		if (!p?.source) return { kind: 'missing', label: '缺失' };
		return { kind: 'sourced', label: '有来源' };
	}
</script>

<svelte:head>
	<title>{data ? `${data.name_zh_cn ?? data.name_en} · DigiDex` : 'DigiDex'}</title>
</svelte:head>

{#if loading}
	<div class="spinner" aria-label="加载中"></div>
{:else if error}
	<div class="error-box" role="alert">{error}</div>
{:else if data}
	<div class="breadcrumb" aria-label="面包屑">
		<a href="/">首页</a><span class="sep">/</span>
		<a href="/">图鉴</a><span class="sep">/</span>
		<span class="cur mono">{data?.canonical_slug ?? slug}</span>
	</div>
	<div class="detail-hero">
		<div class="detail-art">
			<button
				class="fav {isFavorite(data.id) ? 'on' : ''}"
				aria-label={isFavorite(data.id) ? '取消收藏' : '收藏'}
				onclick={() => toggleFavorite(data!.id)}
			>{isFavorite(data.id) ? '★' : '☆'}</button>
			<PlaceholderImage
				src={data.main_image ? api.mainUrl(data.id) : null}
				alt={data.name_zh_cn ?? data.name_en ?? ''}
				label={data.name_en ?? 'NO IMAGE'}
				loading="eager"
			/>
			{#if imageStatus}
				<div class="img-status {imageStatus.kind}" role="status">{imageStatus.text}</div>
			{/if}
		</div>
		<div class="detail-main">
			<div class="detail-id mono">#{data.id} · {data.canonical_slug}</div>
			<h1 class="detail-h1">
				{data.names.zh_cn ?? '—'}
				{#if data.names.zh_cn_status === 'transliteration' || data.names.zh_cn_status === 'unverified'}
					<span class="name-tag" style="font-size:11px;vertical-align:8px" title="此中文名为音译/自动生成，未验证，非官方定名">音译·未验证</span>
				{/if}
				{#if data.names.ja}<span class="ja">{data.names.ja}</span>{/if}
			</h1>
			<div class="detail-sub">
				{#if data.names.en}<span>{data.names.en}</span>{/if}
				{#if data.names.romanized && data.names.romanized !== data.names.en}
					<span class="faint"> · {data.names.romanized}</span>
				{/if}
				{#if data.names.en_dub}<span class="faint"> · Dub: {data.names.en_dub}</span>{/if}
				{#if data.names.zh_hk}<span class="faint"> · 港译 {data.names.zh_hk}</span>{/if}
				{#if data.names.zh_tw}<span class="faint"> · 台译 {data.names.zh_tw}</span>{/if}
			</div>

			<div class="detail-badges">
				<Badges level={data.level} attribute={data.attribute} />
				{#if data.x_antibody}
					<span class="badge" style="color:var(--accent);background:rgba(53,208,255,0.14)">X 抗体</span>
				{/if}
				{#if data.is_official_reference}
					<span class="badge" style="color:var(--green);background:rgba(94,242,160,0.12)">官方图鉴</span>
				{:else}
					<span class="badge" style="color:var(--gold);background:rgba(255,200,87,0.12)">扩展图鉴</span>
				{/if}
			</div>

			{#if data.aliases.length > 0}
				<div class="alias-block">
					<span class="faint mono" style="font-size:11px">别名</span>
					<div class="alias-list">
						{#each data.aliases as a}
							<span class="alias-chip" title={`${a.alias_type}${a.language ? ` · ${a.language}` : ''}${a.source ? ` · ${a.source}` : ''}`}>
								{a.alias}
							</span>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	</div>

	<div class="section-title">基本信息</div>
	<div class="basic-grid">
		<div class="basic-cell"><div class="k">等级 Level</div><div class="v">
			{levelLabel(data.level ?? 'unknown')}
			{#if data.level_2}<span class="xros-tag">{data.level_2}</span>{/if}
		</div></div>
		<div class="basic-cell"><div class="k">属性 Attribute</div><div class="v">{attrLabel(data.attribute ?? 'unknown')}</div></div>
		{#if data.types.length}
			<div class="basic-cell">
				<div class="k">类型 Type</div>
				<div class="v">{data.types.map((t) => t.name).join(' / ')}</div>
			</div>
		{/if}
		{#if data.first_appearance.date || data.first_appearance.title}
			<div class="basic-cell">
				<div class="k">首次登场</div>
				<div class="v">
					{#if data.first_appearance.title}
						{data.first_appearance.title}{data.first_appearance.medium ? `（${data.first_appearance.medium}）` : ''}
					{:else}
						<span class="faint">标题未记录</span>
					{/if}
					{#if data.first_appearance.date}
						<span class="faint"> · {data.first_appearance.date}</span>
					{/if}
				</div>
			</div>
		{/if}
		{#if data.fields.length}
			<div class="basic-cell">
				<div class="k">适应领域 Field</div>
				<div class="v">
					{#each data.fields as f}<span class="field-pill">{f.name}</span>{/each}
				</div>
			</div>
		{/if}
		{#if data.groups.length}
			<div class="basic-cell">
				<div class="k">所属组织 Group</div>
				<div class="v">
					{#each data.groups as g}
						<a class="group-pill" href={`/group/${encodeURIComponent(g.name)}`}>{g.name_zh ?? g.name}</a>
					{/each}
				</div>
			</div>
		{/if}
	</div>

	{#if data.profile.zh_cn || data.profile.en || data.profile.ja}
		<div class="section-title">简介 Profile</div>
		<div class="profile-block">
			{#if data.profile.zh_cn}
				<p>{data.profile.zh_cn}</p>
			{:else}
				<p class="no-data">暂无可靠中文简介</p>
			{/if}
			{#if data.profile.en}
				<details><summary class="faint">English Profile</summary><p>{data.profile.en}</p></details>
			{/if}
			{#if data.profile.ja}
				<details><summary class="faint">日本語プロフィール</summary><p>{data.profile.ja}</p></details>
			{/if}
		</div>
	{/if}

	<div class="section-title">必杀技 / 技能 Skills</div>
	{#if data.skills.length > 0}
		<div class="skill-list">
			{#each data.skills as s}
				<div class="skill-item">
					<div class="skill-name">
						{#if s.name_zh_cn}<span class="s-zh">{s.name_zh_cn}</span>{/if}
						{#if s.name_en}<span class="s-en">{s.name_en}</span>{/if}
						{#if s.name_ja}<span class="s-ja">{s.name_ja}</span>{/if}
						{#if s.is_signature}<span class="sig">代表技</span>{/if}
					</div>
					{#if s.description_zh_cn}<div class="s-desc">{s.description_zh_cn}</div>{/if}
					{#if s.description_en && !s.description_zh_cn}<div class="s-desc dim">{s.description_en}</div>{/if}
				</div>
			{/each}
		</div>
	{:else}
		<div class="no-data">暂无可靠技能资料</div>
	{/if}

	<div class="section-title">进化 Evolution</div>
	{#if evoLoading}
		<div class="evo-status">
			<span class="spinner" aria-label="进化图加载中"></span>
			<span class="faint">正在加载深度 {evoDepth + 1} 的进化关系…</span>
		</div>
	{:else if evoError}
		<div class="error-box" role="alert">{evoError}</div>
		<div class="evo-status">
			<button class="btn" onclick={expandEvo}>重试展开</button>
		</div>
	{/if}
	{#if data.evolution.truncated}
		<div class="evo-status warn" role="status">
			进化关系规模较大，仅展示部分关系：{data.evolution.node_count} 节点 / {data.evolution.edge_count} 边，另有 {data.evolution.dropped_edges} 条未展示。
			建议使用较浅深度查看。
		</div>
	{/if}
	<EvolutionGraph
		graph={data.evolution}
		centerId={data.id}
		canExpand={evoDepth < MAX_EVO_DEPTH && !evoLoading}
		onExpand={expandEvo}
	/>
	<div class="faint mono" style="font-size:11px;margin-top:6px">
		当前深度 {data.evolution.depth ?? evoDepth} / 最大 {MAX_EVO_DEPTH} ·
		{data.evolution.node_count ?? 0} 节点 / {data.evolution.edge_count ?? 0} 边
		{#if data.evolution.truncated}
			（截断）
		{/if}
	</div>
	{#if evoDepth > 1}
		<div class="evo-status">
			<button class="btn" onclick={() => setDepth(1)}>回到深度 1</button>
			{#if evoDepth === 3}
				<button class="btn" onclick={() => setDepth(2)}>回到深度 2</button>
			{/if}
		</div>
	{/if}

	{#if data.game_stats.length > 0}
		<div class="section-title">游戏数据 Game Stats</div>
		<div class="faint" style="font-size:12px;margin-bottom:8px">
			世界观属性与游戏数值完全分离（规格 §10）。以下为该游戏内的独立数值。
		</div>
		{#each data.game_stats as gs}
			<details class="game-block" open>
				<summary>{gs.game}</summary>
				<div class="stat-grid-small">
					{#if gs.hp !== null}<span class="gs-cell"><span class="k">HP</span><span class="v">{gs.hp}</span></span>{/if}
					{#if gs.sp !== null}<span class="gs-cell"><span class="k">SP</span><span class="v">{gs.sp}</span></span>{/if}
					{#if gs.atk !== null}<span class="gs-cell"><span class="k">ATK</span><span class="v">{gs.atk}</span></span>{/if}
					{#if gs.def !== null}<span class="gs-cell"><span class="k">DEF</span><span class="v">{gs.def}</span></span>{/if}
					{#if gs.int !== null}<span class="gs-cell"><span class="k">INT</span><span class="v">{gs.int}</span></span>{/if}
					{#if gs.spd !== null}<span class="gs-cell"><span class="k">SPD</span><span class="v">{gs.spd}</span></span>{/if}
					{#if gs.memory !== null}<span class="gs-cell"><span class="k">内存</span><span class="v">{gs.memory}</span></span>{/if}
					{#if gs.slots !== null}<span class="gs-cell"><span class="k">槽位</span><span class="v">{gs.slots}</span></span>{/if}
				</div>
			</details>
		{/each}
	{/if}

	{#if data.relations.length > 0}
		<div class="section-title">相关形态 Related Forms</div>
		<div class="evo-row-wrap">
			{#each data.relations as r}
				<a class="evo-node" href={`/digimon/${r.canonical_slug}`}>
					<span>
						<span class="n-zh">{r.name_zh_cn ?? '—'}</span>
						<span class="n-en">{r.name_en}</span>
						<span class="n-rel">{relTypeLabel(r.relation_type)}</span>
					</span>
				</a>
			{/each}
		</div>
	{/if}

	{#if data.name_origin}
		<div class="section-title">名称来源 Name Origin</div>
		<div class="profile-block">{data.name_origin}</div>
	{/if}

	{#if data.conflicts.length > 0}
		<div class="section-title">字段冲突 Conflicts</div>
		<div class="conflict-list">
			{#each data.conflicts as c}
				<div class="conflict-item">
					<div class="conflict-field mono">{c.field}</div>
					<div class="conflict-vs">
						<span class="faint">{c.source_a}：</span>{c.value_a ?? '—'}
						<span class="faint"> vs </span>
						<span class="faint">{c.source_b}：</span>{c.value_b ?? '—'}
					</div>
					{#if c.resolution}
						<div class="faint" style="font-size:12px">选择：{c.chosen_source} = {c.chosen_value ?? '—'}（{c.resolution}）</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if data.source.length > 0}
		<div class="section-title">数据来源 Source</div>
		<details>
			<summary class="faint">展开查看字段级出处</summary>
			<table class="source-table">
				<thead><tr><th>字段</th><th>状态</th><th>来源</th><th>URL</th><th>获取时间</th></tr></thead>
				<tbody>
					{#each data.source as p}
						{@const st = fieldStatus(p.field)}
						<tr>
							<td>{p.field}</td>
							<td><span class="prov-status {st.kind}">{st.label}</span></td>
							<td>{p.source ?? '—'}</td>
							<td>
							{#if p.source_url}<a href={p.source_url} target="_blank" rel="noopener">{p.source_url}</a>{:else}—{/if}
						</td>
							<td>{p.retrieved_at ?? '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</details>
	{/if}
{/if}

<style>
	.alias-block {
		margin-top: 14px;
	}
	.alias-list {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		margin-top: 4px;
	}
	.alias-chip {
		font-size: 12px;
		color: var(--text-dim);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 2px 9px;
	}
	.field-pill,
	.group-pill {
		display: inline-block;
		margin: 1px 4px 1px 0;
		font-size: 12.5px;
		color: var(--text-dim);
	}
	.group-pill:hover {
		color: var(--accent);
	}
	.skill-list {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.skill-item {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 12px 16px;
	}
	.skill-name {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 10px;
	}
	.s-zh {
		font-weight: 700;
		font-size: 15px;
	}
	.s-en {
		font-family: var(--mono);
		color: var(--text-dim);
		font-size: 12.5px;
	}
	.s-ja {
		color: var(--text-dim);
		font-size: 13px;
	}
	.sig {
		font-family: var(--mono);
		font-size: 10px;
		color: var(--accent);
		border: 1px solid rgba(53, 208, 255, 0.4);
		border-radius: 999px;
		padding: 1px 7px;
	}
	.s-desc {
		margin-top: 6px;
		font-size: 13.5px;
		color: var(--text-dim);
	}
	.evo-row-wrap {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.evo-node {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		background: var(--surface-2);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		padding: 6px 12px;
		transition: border-color 0.12s;
	}
	.evo-node:hover {
		border-color: var(--accent);
	}
	.n-zh {
		font-weight: 700;
		font-size: 13px;
		display: block;
	}
	.n-en {
		font-family: var(--mono);
		font-size: 11px;
		color: var(--text-dim);
		display: block;
	}
	.n-rel {
		font-size: 10.5px;
		color: var(--accent);
		display: block;
	}
	.source-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
		margin-top: 8px;
	}
	.source-table th,
	.source-table td {
		border: 1px solid var(--border);
		padding: 5px 8px;
		text-align: left;
		vertical-align: top;
	}
	.source-table th {
		background: var(--surface-2);
		color: var(--text-faint);
		font-family: var(--mono);
		font-weight: 500;
	}
	details summary {
		cursor: pointer;
	}
	.game-block {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 10px 14px;
		margin-bottom: 8px;
	}
	.game-block summary {
		font-weight: 700;
		font-size: 13px;
		color: var(--text-dim);
	}
	.stat-grid-small {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
		gap: 8px;
		margin-top: 10px;
	}
	.gs-cell {
		background: var(--surface-2);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		padding: 6px 8px;
		text-align: center;
	}
	.gs-cell .k {
		font-family: var(--mono);
		font-size: 10px;
		color: var(--text-faint);
		display: block;
	}
	.gs-cell .v {
		font-size: 15px;
		font-weight: 700;
		color: var(--accent);
	}
	.xros-tag {
		display: inline-block;
		margin-left: 6px;
		font-size: 11px;
		font-weight: 600;
		color: var(--gold);
		background: rgba(255, 200, 87, 0.12);
		border: 1px solid rgba(255, 200, 87, 0.4);
		border-radius: 999px;
		padding: 1px 8px;
	}
	.evo-status {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 12.5px;
		margin: 8px 0;
	}
	.evo-status .spinner {
		width: 14px;
		height: 14px;
	}
	.evo-status.warn {
		color: var(--gold);
		background: rgba(255, 200, 87, 0.08);
		border: 1px solid rgba(255, 200, 87, 0.3);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
	}
	.img-status {
		margin-top: 8px;
		font-size: 11px;
		text-align: center;
		color: var(--text-faint);
	}
	.img-status.downloaded {
		color: var(--green);
	}
	.img-status.failed,
	.img-status.missing {
		color: var(--gold);
	}
	.conflict-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 12px;
	}
	.conflict-item {
		background: rgba(255, 200, 87, 0.06);
		border: 1px solid rgba(255, 200, 87, 0.3);
		border-radius: var(--radius-sm);
		padding: 8px 12px;
		font-size: 13px;
	}
	.conflict-field {
		font-size: 11px;
		color: var(--gold);
		margin-bottom: 2px;
	}
	.prov-status {
		display: inline-block;
		font-size: 11px;
		padding: 0 7px;
		border-radius: 999px;
		border: 1px solid var(--border);
		color: var(--text-dim);
		white-space: nowrap;
	}
	.prov-status.sourced {
		color: var(--green);
		border-color: rgba(94, 242, 160, 0.35);
	}
	.prov-status.conflict {
		color: var(--gold);
		border-color: rgba(255, 200, 87, 0.4);
	}
	.prov-status.missing {
		color: var(--text-faint);
	}
</style>
