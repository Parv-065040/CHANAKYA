const API = import.meta.env.VITE_API_URL || "";

async function request(path, options = {}) {
  const response = await fetch(API + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.error?.message || `Request failed (${response.status})`);
  return payload;
}

export async function getHealth() { return request("/health"); }
export async function getDocuments() {
  const docs = await request("/documents");
  return Array.isArray(docs) ? docs.map((doc) => ({
    ...doc,
    chunks: Number(doc.n_chunks ?? doc.chunks ?? 0),
    tables: Number(doc.n_tables ?? doc.tables ?? 0),
    pages: Number(doc.pages ?? 0),
  })) : [];
}
export async function getEvaluation() {
  try { return await request("/evaluation/summary"); } catch { return null; }
}
export async function queryChanakya(question, department = null) {
  return request("/query", { method: "POST", body: JSON.stringify({ question, department }) });
}
export async function getSource(chunkId) { return request("/sources/" + encodeURIComponent(chunkId)); }
