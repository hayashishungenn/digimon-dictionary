// Minimal API client for the DigiDex backend.
import type {
	DigimonDetail,
	DigimonListItem,
	EvolutionGraph,
	GroupResponse,
	ListResponse,
	Meta,
	SearchResponse,
	Skill,
} from './types';

const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';
const API_ORIGIN: string = API_BASE.replace(/\/api$/, '');

async function get<T>(path: string): Promise<T> {
	const res = await fetch(`${API_BASE}${path}`);
	if (!res.ok) {
		const body = await res.text().catch(() => '');
		throw new ApiError(res.status, body || res.statusText);
	}
	return (await res.json()) as T;
}

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

export interface ListFilters {
	level?: string | null;
	attribute?: string | null;
	type?: string | null;
	field?: string | null;
	group?: string | null;
	x_antibody?: boolean | null;
	official?: 'all' | 'official' | 'extended';
	sort?: string;
	order?: 'asc' | 'desc';
	limit?: number;
	offset?: number;
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
	const sp = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== null && v !== undefined && v !== '' && v !== 'all') sp.set(k, String(v));
	}
	const s = sp.toString();
	return s ? `?${s}` : '';
}

export const api = {
	meta: () => get<Meta>('/meta'),
	list: (filters: ListFilters) => get<ListResponse>(`/digimon${qs(filters as never)}`),
	detail: (ident: string) => get<DigimonDetail>(`/digimon/${ident}`),
	search: (q: string, limit = 30) => get<SearchResponse>(`/search?q=${encodeURIComponent(q)}&limit=${limit}`),
	evolution: (ident: string, depth = 1) => get<EvolutionGraph>(`/digimon/${ident}/evolution?depth=${depth}`),
	skills: (ident: string) => get<Skill[]>(`/digimon/${ident}/skills`),
	group: (name: string) => get<GroupResponse>(`/groups/${encodeURIComponent(name)}`),
	byIds: (ids: number[]) => get<{ items: DigimonListItem[] }>(`/digimon/by-id?ids=${ids.join(',')}`),
	// Resolve an API-relative image path (e.g. "/api/images/agumon/thumbnail")
	// to an absolute URL the browser can load.
	imageUrl: (path: string | null | undefined): string | null => {
		if (!path) return null;
		return path.startsWith('http') ? path : `${API_ORIGIN}${path}`;
	},
	// Direct cached-image URLs (P0-3): served by the API, fall back to the
	// source URL server-side, and 404 into the placeholder when absent.
	thumbUrl: (ident: string | number) => `${API_BASE}/images/${ident}/thumbnail`,
	mainUrl: (ident: string | number) => `${API_BASE}/images/${ident}/main_image`,
};

// Debounced search helper for the search bar.
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
	let t: ReturnType<typeof setTimeout> | undefined;
	return (...args: A) => {
		if (t) clearTimeout(t);
		t = setTimeout(() => fn(...args), ms);
	};
}
