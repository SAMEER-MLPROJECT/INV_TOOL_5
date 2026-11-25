async function request(path, options = {}) {
  const response = await fetch(path, { headers: { Accept: "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (error) {
      detail = detail || String(error);
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  cases: () => request("/api/cases"),
  bundle: (caseId) => request(`/api/cases/${encodeURIComponent(caseId)}`),
  reach: (caseId, asOf, policy) => {
    const params = new URLSearchParams();
    if (asOf !== null && asOf !== undefined) params.set("as_of", String(asOf));
    if (policy) params.set("policy", policy);
    return request(`/api/cases/${encodeURIComponent(caseId)}/reach?${params}`);
  },
  link: (caseId, linkId) => request(`/api/cases/${encodeURIComponent(caseId)}/links/${encodeURIComponent(linkId)}`),
  observation: (caseId, obsId) => request(`/api/cases/${encodeURIComponent(caseId)}/observations/${encodeURIComponent(obsId)}`),
  act: (caseId, body) =>
    request(`/api/cases/${encodeURIComponent(caseId)}/actions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  upload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/cases", { method: "POST", body: form });
  },
  evaluation: () => request("/api/evaluation"),
};
