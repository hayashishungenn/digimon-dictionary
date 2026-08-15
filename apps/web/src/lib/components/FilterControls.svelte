<script lang="ts">
	// Shared filter controls (attribute / type / field / group / X-Antibody /
	// sort). Rendered inline on desktop and inside the mobile filter drawer —
	// one source of truth for the filter markup (UI-P0-2).
	import { metaState } from '$lib/stores/meta.svelte';

	interface Props {
		attribute?: string | null;
		typeName?: string | null;
		field?: string | null;
		group?: string | null;
		xAb?: boolean | null;
		sort?: string;
	}
	let {
		attribute = $bindable(null),
		typeName = $bindable(null),
		field = $bindable(null),
		group = $bindable(null),
		xAb = $bindable(null),
		sort = $bindable('name')
	}: Props = $props();
</script>

<label class="f-control">
	<span class="f-label">属性</span>
	<select class="select" value={attribute ?? ''} onchange={(e) => (attribute = (e.target as HTMLSelectElement).value || null)}>
		<option value="">全部</option>
		{#each metaState.meta?.attributes ?? [] as a}
			<option value={a.value}>{a.label_zh} / {a.label_en}</option>
		{/each}
	</select>
</label>

<label class="f-control">
	<span class="f-label">类型</span>
	<select class="select" value={typeName ?? ''} onchange={(e) => (typeName = (e.target as HTMLSelectElement).value || null)}>
		<option value="">全部</option>
		{#each metaState.meta?.types ?? [] as t}
			<option value={t.name}>{t.name}</option>
		{/each}
	</select>
</label>

<label class="f-control">
	<span class="f-label">适应领域</span>
	<select class="select" value={field ?? ''} onchange={(e) => (field = (e.target as HTMLSelectElement).value || null)}>
		<option value="">全部</option>
		{#each metaState.meta?.fields ?? [] as f}
			<option value={f.name}>{f.name}</option>
		{/each}
	</select>
</label>

<label class="f-control">
	<span class="f-label">所属组织</span>
	<select class="select" value={group ?? ''} onchange={(e) => (group = (e.target as HTMLSelectElement).value || null)}>
		<option value="">全部</option>
		{#each metaState.meta?.groups ?? [] as g}
			<option value={g.name}>{g.name_zh ? `${g.name_zh} · ${g.name}` : g.name}</option>
		{/each}
	</select>
</label>

<label class="f-control">
	<span class="f-label">X 抗体</span>
	<select class="select" value={xAb === null ? '' : String(xAb)} onchange={(e) => {
		const v = (e.target as HTMLSelectElement).value;
		xAb = v === '' ? null : v === 'true';
	}}>
		<option value="">全部</option>
		<option value="true">是</option>
		<option value="false">否</option>
	</select>
</label>

<label class="f-control">
	<span class="f-label">排序</span>
	<select class="select" value={sort} onchange={(e) => (sort = (e.target as HTMLSelectElement).value)}>
		<option value="name">名称</option>
		<option value="id">ID</option>
		<option value="debut">首次登场</option>
		<option value="recent">最近更新</option>
		<option value="level">等级</option>
	</select>
</label>
