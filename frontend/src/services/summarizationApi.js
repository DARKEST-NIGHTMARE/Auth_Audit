import api from "./api";

export const summarizationApi = {
    query: async (text) => {
        const response = await api.post("/api/summarize/query", { text });
        return response.data;
    },

    autocomplete: async (q) => {
        const response = await api.get(`/api/summarize/autocomplete?q=${encodeURIComponent(q)}`);
        return response.data;
    },

    ingestFile: async (fileId) => {
        const response = await api.post(`/api/summarize/ingest/${fileId}`);
        return response.data;
    },

    ingestFolder: async (folderId) => {
        const response = await api.post(`/api/summarize/ingest-folder/${folderId}`);
        return response.data;
    },

    getStatus: async () => {
        const response = await api.get("/api/summarize/status");
        return response.data;
    },

    getResult: async (jobId) => {
        const response = await api.get(`/api/summarize/result/${jobId}`);
        return response.data;
    },
};
