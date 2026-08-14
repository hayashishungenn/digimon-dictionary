// Shared TypeScript types for the DigiDex API contract.
// Keep in sync with apps/api/main.py + apps/api/queries.py.

export interface LevelMeta {
	value: string;
	label_zh: string;
	label_en: string;
}

export interface AttributeMeta {
	value: string;
	label_zh: string;
	label_en: string;
}

export interface TypeMeta {
	id: number;
	name: string;
	name_zh: string | null;
	name_ja: string | null;
}

export interface FieldMeta {
	id: number;
	name: string;
	name_zh: string | null;
	name_ja: string | null;
}

export interface GroupMeta {
	id: number;
	name: string;
	name_zh: string | null;
}

export interface Snapshot {
	snapshot_date: string | null;
	official_count: number | null;
	extended_count: number | null;
	total_count: number | null;
}

export interface Meta {
	snapshot: Snapshot | null;
	counts: { total: number; official: number; extended: number };
	levels: LevelMeta[];
	attributes: AttributeMeta[];
	types: TypeMeta[];
	fields: FieldMeta[];
	groups: GroupMeta[];
}

export interface DigimonListItem {
	id: number;
	canonical_slug: string;
	name_zh_cn: string | null;
	name_en: string | null;
	name_ja: string | null;
	name_zh_cn_status: string | null;
	level: string | null;
	attribute: string | null;
	x_antibody: boolean;
	is_official_reference: boolean;
	is_extended: boolean;
	main_image: string | null;
	thumbnail: string | null;
	first_appearance_date: string | null;
	updated_at: string | null;
}

export interface Skill {
	id: number;
	name_zh_cn: string | null;
	name_en: string | null;
	name_ja: string | null;
	description_zh_cn: string | null;
	description_en: string | null;
	description_ja: string | null;
	skill_type: string;
	is_signature: boolean;
	sort_order: number;
}

export interface Alias {
	alias: string;
	language: string | null;
	region: string | null;
	alias_type: string;
	source: string | null;
	verified: boolean;
}

export interface Image {
	image_type: string;
	remote_url: string | null;
	local_path: string | null;
	download_status: string;
	width: number | null;
	height: number | null;
	transparent: boolean | null;
	sha256: string | null;
}

export interface EvolutionNode {
	id: number;
	canonical_slug: string;
	name_zh_cn: string | null;
	name_en: string | null;
	name_ja: string | null;
	level: string | null;
	main_image: string | null;
}

export interface EvolutionEdge {
	id: number;
	from: number;
	to: number;
	evolution_type: string;
	condition: string | null;
	is_primary_line: boolean;
	source: string | null;
}

export interface EvolutionGraph {
	center: number;
	nodes: Record<string, EvolutionNode>;
	edges: EvolutionEdge[];
}

export interface Relation {
	relation_type: string;
	source: string | null;
	note: string | null;
	to_id: number;
	canonical_slug: string;
	name_zh_cn: string | null;
	name_en: string | null;
}

export interface GameStats {
	game: string;
	short_name: string;
	hp: number | null;
	sp: number | null;
	atk: number | null;
	def: number | null;
	int: number | null;
	spd: number | null;
	memory: number | null;
	slots: number | null;
	extras: string | null;
	source: string | null;
}

export interface Provenance {
	field: string;
	source: string | null;
	source_url: string | null;
	retrieved_at: string | null;
	confidence: string | null;
}

export interface DigimonDetail extends DigimonListItem {
	types: Array<{ name: string; name_zh: string | null; name_ja: string | null; is_primary: boolean; source: string | null }>;
	fields: Array<{ name: string; name_zh: string | null }>;
	groups: Array<{ name: string; name_zh: string | null }>;
	skills: Skill[];
	aliases: Alias[];
	images: Image[];
	game_stats: GameStats[];
	evolution: EvolutionGraph;
	relations: Relation[];
	profile: {
		zh_cn: string | null;
		en: string | null;
		ja: string | null;
		source: string | null;
		source_url: string | null;
		verified: boolean;
	};
	first_appearance: {
		title: string | null;
		date: string | null;
		medium: string | null;
	};
	name_origin: string | null;
	names: {
		zh_cn: string | null;
		zh_cn_status: string | null;
		zh_hk: string | null;
		zh_tw: string | null;
		en: string | null;
		en_dub: string | null;
		ja: string | null;
		romanized: string | null;
	};
	source: Provenance[];
}

export interface ListResponse {
	items: DigimonListItem[];
	total: number;
	limit: number;
	offset: number;
}

export interface SearchResponse {
	query: string;
	items: DigimonListItem[];
	count: number;
}

export interface GroupResponse {
	name: string;
	members: DigimonListItem[];
	count: number;
}
