import api from "./api";

export const googleDriveApi = {
    getAuthUrl: async () => {
        const response = await api.get("/drive/auth-url");
        return response.data;
    },

    connectDrive: async (code) => {
        const response = await api.post("/drive/callback", { code });
        return response.data;
    },

    getStatus: async () => {
        const response = await api.get("/drive/status");
        return response.data;
    },

    disconnectDrive: async () => {
        const response = await api.delete("/drive/disconnect");
        return response.data;
    },

    getFolders: async () => {
        const response = await api.get("/drive/folders");
        return response.data;
    },

    analyzeFolder: async (folderId) => {
        const response = await api.get(`/drive/folders/${folderId}/analyze`);
        return response.data;
    }
};
