// Minimal API client for the DigiDex backend.
import type {
	DigimonDetail,
	DigimonListItem,
	EvolutionGraph,
	GroupResponse,
	ListResponse,
	Meta,
	ResolveReviewResponse,
	ReviewCategory,
	ReviewListResponse,
	ReviewStats,
	ReviewStatus,
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

// P1-3: the review resolve endpoint is the only write the UI makes; JSON body,
// same ApiError contract as get() so userMessage() maps 404/409/422/5xx.
async function post<T>(path: string, body: unknown): Promise<T> {
	const res = await fetch(`${API_BASE}${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
	if (!res.ok) {
		const text = await res.text().catch(() => '');
		throw new ApiError(res.status, text || res.statusText);
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

// Map a thrown error to a safe, user-facing message (never a raw stack/SQL/
// path). Network failure and server errors get friendly text (UI-P1-1).
export function userMessage(e: unknown, fallback: string): string {
	if (e instanceof ApiError) {
		if (e.status === 404) return '没有找到该条目（可能已被移除）。';
		if (e.status === 503) return '数据服务尚未同步。请先运行 sync-data 再访问。';
		if (e.status >= 500) return '数据服务暂时不可用，请稍后重试。';
		return fallback;
	}
	if (e instanceof TypeError) return '无法连接数据服务，请确认后端已启动。';
	return fallback;
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

export interface ReviewListFilters {
	status?: ReviewStatus;
	entity_type?: string | null;
	q?: string | null;
	category?: ReviewCategory | null;
	limit?: number;
	offset?: number;
}

export interface ReviewExportFilters {
	format?: 'json' | 'csv';
	status?: ReviewStatus;
	entity_type?: string | null;
	q?: string | null;
	category?: ReviewCategory | null;
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
	review: (filters: ReviewListFilters = {}) =>
		get<ReviewListResponse>(
			`/review${qs({
				status: filters.status,
				entity_type: filters.entity_type,
				q: filters.q,
				category: filters.category,
				limit: filters.limit,
				offset: filters.offset,
			})}`
		),
	reviewStats: () => get<ReviewStats>('/review/stats'),
	resolveReview: (id: number, status: Exclude<ReviewStatus, 'open'>, note: string) =>
		post<ResolveReviewResponse>(`/review/${id}/resolve`, { status, note }),
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

export function reviewExportUrl(filters: ReviewExportFilters = {}): string {
	return `${API_BASE}/review/export${qs({
		format: filters.format ?? 'json',
		status: filters.status,
		entity_type: filters.entity_type,
		q: filters.q,
		category: filters.category,
	})}`;
}

// Debounced search helper for the search bar.
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): (...args: A) => void {
	let t: ReturnType<typeof setTimeout> | undefined;
	return (...args: A) => {
		if (t) clearTimeout(t);
		t = setTimeout(() => fn(...args), ms);
	};
}
