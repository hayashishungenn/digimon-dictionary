// Personal research data: per-digimon notes, tags, and query history.
// Purely local (localStorage) — NEVER part of the canonical database, never
// shown in the official provenance/source tables, survives syncs (S2-1 / UI-P2-1).
const KEY = 'digidex.personal.v1';
const MAX_HISTORY = 20;

type Personal = {
	notes: Record<number, string>;
	tags: Record<number, string[]>;
	history: string[];
};

function empty(): Personal {
	return { notes: {}, tags: {}, history: [] };
}

function load(): Personal {
	if (typeof localStorage === 'undefined') return empty();
	try {
		const raw = localStorage.getItem(KEY);
		if (!raw) return empty();
		const d = JSON.parse(raw);
		if (typeof d !== 'object' || d === null) return empty();
		return {
			notes: typeof d.notes === 'object' && d.notes ? d.notes : {},
			tags: typeof d.tags === 'object' && d.tags ? d.tags : {},
			history: Array.isArray(d.history) ? d.history.filter((x: unknown) => typeof x === 'string') : []
		};
	} catch {
		return empty(); // corrupted localStorage -> safe empty state
	}
}

function save(state: Personal) {
	try {
		localStorage.setItem(KEY, JSON.stringify(state));
	} catch {
		// quota / privacy-mode — ignore, in-memory state still works
	}
}

export const personal = $state<Personal>(load());

export function setNote(id: number, text: string): void {
	const t = text.trim();
	if (t) personal.notes[id] = t;
	else delete personal.notes[id];
	save(personal);
}

export function getNote(id: number): string {
	return personal.notes[id] ?? '';
}

export function addTag(id: number, tag: string): boolean {
	const t = tag.trim();
	if (!t) return false;
	const list = personal.tags[id] ?? [];
	if (list.includes(t)) return false;
	list.push(t);
	personal.tags[id] = list;
	save(personal);
	return true;
}

export function removeTag(id: number, tag: string): void {
	const list = personal.tags[id] ?? [];
	const i = list.indexOf(tag);
	if (i >= 0) list.splice(i, 1);
	if (list.length === 0) delete personal.tags[id];
	else personal.tags[id] = list;
	save(personal);
}

export function getTags(id: number): string[] {
	return personal.tags[id] ?? [];
}

export function recordQuery(q: string): void {
	const t = q.trim();
	if (!t) return;
	personal.history = [t, ...personal.history.filter((x) => x !== t)].slice(0, MAX_HISTORY);
	save(personal);
}

export function clearHistory(): void {
	personal.history = [];
	save(personal);
}

export function clearPersonal(): void {
	personal.notes = {};
	personal.tags = {};
	personal.history = [];
	save(personal);
}

/** Count of personal records (notes/tags) for a given digimon. */
export function personalCount(id: number): number {
	return (personal.notes[id] ? 1 : 0) + (personal.tags[id]?.length ?? 0);
}
