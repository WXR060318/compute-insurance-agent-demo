export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
 const response = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
 if (!response.ok) {
   const body = await response.json().catch(() => null);
   const detail = body?.detail;
   const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg).join('；') : '服务返回 ' + response.status;
   throw new Error(message);
 }
 return response.json() as Promise<T>;
}
export const num = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
export const money = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : '¥' + value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const timeOf = (value: string | null | undefined) => value ? new Date(value).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }) : '—';
export const dateTime = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
