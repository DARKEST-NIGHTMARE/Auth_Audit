import api from "./api";

export const googleDriveApi = {
    getAuthUrl: async () => {
        const redirectUri = window.location.origin + "/drive/callback";
        const response = await api.get(`/api/drive/auth-url?redirect_uri=${encodeURIComponent(redirectUri)}`);
        return response.data;
    },

    connectDrive: async (code) => {
        const redirectUri = window.location.origin + "/drive/callback";
        const response = await api.post("/api/drive/callback", { code, redirect_uri: redirectUri });
        return response.data;
    },

    createFolder: async (name, parentId = null) => {
        const response = await api.post("/api/drive/create-folder", { name, parent_id: parentId });
        return response.data;
    },

    createFile: async (name, content, parentId = null) => {
        const response = await api.post("/api/drive/create-file", { name, content, parent_id: parentId });
        return response.data;
    },

    deleteItem: async (itemId) => {
        const response = await api.delete(`/api/drive/items/${itemId}`);
        return response.data;
    },

    uploadFile: async (file, parentId = null) => {
        const formData = new FormData();
        formData.append("file", file);
        if (parentId) {
            formData.append("parent_id", parentId);
        }
        const response = await api.post("/api/drive/upload-file", formData, {
            headers: {
                "Content-Type": "multipart/form-data"
            }
        });
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
