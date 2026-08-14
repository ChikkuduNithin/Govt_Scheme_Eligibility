export const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const WS_BASE =
  import.meta.env.VITE_WS_URL ?? "http://localhost:8000/ws";

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (data.detail) {
        detail =
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail);
      }
    } catch {
      // response body was not JSON; keep the generic message
    }
    throw new Error(detail);
  }

  return response.json();
}

export function hospitalWsUrl(hospitalId) {
  return WS_BASE.replace(/^http/, "ws") + `/hospital/${hospitalId}`;
}
