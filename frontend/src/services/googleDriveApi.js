import api from "./api";

export const googleDriveApi = {
    getAuthUrl: async () => {
        const response = await api.get("/api/drive/auth-url");
        return response.data;
    },

    connectDrive: async (code) => {
        const response = await api.post("/api/drive/callback", { code });
        return response.data;
    },

    createFolder: async (name) => {
        const response = await api.post("/api/drive/create-folder", null, { params: { name } });
        return response.data;
    },

    getStatus: async () => {
        const response = await api.get("/api/drive/status");
        return response.data;
    },

    disconnectDrive: async () => {
        const response = await api.delete("/api/drive/disconnect");
        return response.data;
    },

    getFolders: async () => {
        const response = await api.get("/api/drive/folders");
        return response.data;
    },

    analyzeFolder: async (folderId) => {
        const response = await api.get(`/api/drive/folders/${folderId}/analyze`);
        return response.data;
    }
};
