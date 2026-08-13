<script lang="ts">
	// Level + attribute badges, colored by canonical enum value (see app.css).
	interface Props {
		level?: string | null;
		attribute?: string | null;
	}
	let { level, attribute }: Props = $props();
</script>

<div class="badges">
	{#if level && level !== 'unknown'}
		<span class="badge level-badge lv-{level}"><span class="badge-dot"></span>Level {levelLabel(level)}</span>
	{:else if level === 'unknown'}
		<span class="badge level-badge lv-unknown">Level 不明</span>
	{/if}
	{#if attribute && attribute !== 'unknown'}
		<span class="badge attr-badge at-{attribute}"><span class="badge-dot"></span>{attrLabel(attribute)}</span>
	{:else if attribute === 'unknown'}
		<span class="badge attr-badge at-unknown">属性不明</span>
	{/if}
</div>

<style>
	.badges {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
</style>

<script module lang="ts">
	export function levelLabel(v: string): string {
		const map: Record<string, string> = {
			digi_egg: '数码蛋',
			baby_i: '幼年期Ⅰ',
			baby_ii: '幼年期Ⅱ',
			child: '成长期',
			adult: '成熟期',
			perfect: '完全体',
			ultimate: '究极体',
			super_ultimate: '超究极体',
			armor: '装甲体',
			hybrid: '混合体',
			unknown: '不明'
		};
		return map[v] ?? v;
	}
	export function attrLabel(v: string): string {
		const map: Record<string, string> = {
			vaccine: '疫苗种',
			virus: '病毒种',
			data: '资料种',
			free: '自由种',
			variable: '可变种',
			unknown: '不明'
		};
		return map[v] ?? v;
	}
</script>
