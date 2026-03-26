import React, { useState, useEffect, useCallback, useMemo } from "react";
import { googleDriveApi } from "../../services/googleDriveApi";
import IntegrationModal from "../common/IntegrationModal";
import FileExplorer from "./FileExplorer";
import DriveLogin from "./DriveLogin";
import WorkspaceGrid from "./WorkspaceGrid";
import WorkspaceFolderView from "./WorkspaceFolderView";
import layoutStyles from "../common/Layout.module.css";

const GoogleDriveManager = () => {
    const [driveConnected, setDriveConnected] = useState(false);
    const [folders, setFolders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [analysis, setAnalysis] = useState(null);
    const [modal, setModal] = useState({ show: false, title: "", type: "input", value: "", confirmText: "OK", onConfirm: null, placeholder: "" });
    const [aiExplorer, setAiExplorer] = useState({ show: false, folderName: "", folderId: null });

    const openModal = (config) => setModal({ ...modal, ...config, show: true });
    const closeModal = () => setModal({ ...modal, show: false, value: "" });

    const fetchFolders = useCallback(async () => {
        try {
            const data = await googleDriveApi.getFolders();
            setFolders(data);
        } catch (err) {
            console.error("Failed to fetch folders", err);
        }
    }, []);

    const checkStatus = useCallback(async () => {
        try {
            setLoading(true);
            const status = await googleDriveApi.getStatus();
            setDriveConnected(status.connected);
            if (status.connected) {
                await fetchFolders();
            }
        } catch (err) {
            console.error("Failed to check Drive status", err);
        } finally {
            setLoading(false);
        }
    }, [fetchFolders]);

    useEffect(() => {
        checkStatus();
    }, [checkStatus]);

    const handleConnect = async () => {
        try {
            const { url } = await googleDriveApi.getAuthUrl();
            window.location.href = url;
        } catch (err) {
            alert("Failed to get auth URL");
        }
    };

    const handleAnalyze = async (folderId) => {
        try {
            setLoading(true);
            const data = await googleDriveApi.analyzeFolder(folderId);
            setAnalysis(data);
        } catch (err) {
            alert("Failed to analyze folder");
        } finally {
            setLoading(false);
        }
    };

    const handleCreateFolder = (parentId = null) => {
        openModal({
            title: "Create New Folder",
            type: "input",
            placeholder: "Enter folder name...",
            value: "New Audit Folder",
            confirmText: "Create",
            onConfirm: async (name) => {
                try {
                    setLoading(true);
                    await googleDriveApi.createFolder(name, parentId);
                    if (parentId) await handleAnalyze(parentId);
                    else await fetchFolders();
                    closeModal();
                } catch (err) {
                    alert("Failed to create folder");
                } finally {
                    setLoading(false);
                }
            }
        });
    };

    const handleCreateFile = (parentId) => {
        openModal({
            title: "Create New File",
            type: "input",
            placeholder: "Enter file name (e.g., audit.txt)...",
            value: "audit_report.txt",
            confirmText: "Create",
            onConfirm: async (name) => {
                try {
                    setLoading(true);
                    await googleDriveApi.createFile(name, "Empty audit report content", parentId);
                    await handleAnalyze(parentId);
                    closeModal();
                } catch (err) {
                    alert("Failed to create file");
                } finally {
                    setLoading(false);
                }
            }
        });
    };

    const handleDelete = (itemId, isFolder = false) => {
        openModal({
            title: "Confirm Delete",
            type: "confirm",
            confirmText: "Safe to Trash",
            onConfirm: async () => {
                try {
                    setLoading(true);
                    await googleDriveApi.deleteItem(itemId);
                    if (analysis && (analysis.folder.id === itemId || analysis.files.some(f => f.id === itemId))) {
                        if (analysis.folder.id === itemId) {
                            setAnalysis(null);
                            await fetchFolders();
                        } else {
                            await handleAnalyze(analysis.folder.id);
                        }
                    } else {
                        await fetchFolders();
                    }
                    closeModal();
                } catch (err) {
                    alert("Failed to delete item");
                } finally {
                    setLoading(false);
                }
            }
        });
    };

    const handleUploadFiles = async (event, parentId = null) => {
        const files = Array.from(event.target.files);
        if (files.length === 0) return;

        try {
            setLoading(true);
            for (const file of files) {
                await googleDriveApi.uploadFile(file, parentId);
            }
            if (parentId) await handleAnalyze(parentId);
            else await fetchFolders();
        } catch (err) {
            alert("Failed to upload files");
        } finally {
            setLoading(false);
        }
    };

    const handleUploadFolder = async (event, parentId = null) => {
        const files = Array.from(event.target.files);
        if (files.length === 0) return;

        try {
            setLoading(true);
            const paths = {};
            for (const file of files) {
                const pathParts = file.webkitRelativePath.split('/');
                const folderName = pathParts[0];
                if (!paths[folderName]) {
                    const folder = await googleDriveApi.createFolder(folderName, parentId);
                    paths[folderName] = folder.id;
                }
                await googleDriveApi.uploadFile(file, paths[folderName]);
            }
            if (parentId) await handleAnalyze(parentId);
            else await fetchFolders();
        } catch (err) {
            console.error(err);
            alert("Failed to upload folder");
        } finally {
            setLoading(false);
        }
    };

    const rootFolders = useMemo(() => {
        return folders.filter(f => !folders.some(p => f.parents?.includes(p.id)));
    }, [folders]);

    if (loading && !folders.length && !analysis) {
        return <div style={{ color: "white", textAlign: "center", padding: "50px" }}>Loading...</div>;
    }

    return (
        <>
        <style>{`
            @media (max-width: 900px) {
                .dashboard-parent {
                    flex-direction: column !important;
                    overflow-y: auto !important;
                }
                .workspace-section {
                    flex: 0 0 auto !important;
                    height: auto !important;
                }
                .ai-section {
                    flex: 0 0 auto !important;
                    height: auto !important;
                    max-width: 100% !important;
                }
            }
        `}</style>
        <div className="dashboard-parent" style={{ 
            display: "flex", 
            flexWrap: "wrap",
            width: "100%", 
            height: "calc(100vh - 250px)",
            minHeight: "600px", 
            overflow: "hidden", 
            gap: aiExplorer.show ? "20px" : "0", 
            transition: "all 0.3s ease"
        }}>
            <div className={`animate-fade-in workspace-section`} style={{ 
                flex: aiExplorer.show ? "1 1 50%" : "1 1 100%", 
                minWidth: "300px", 
                height: "100%", 
                overflowY: "auto", 
                position: "relative",
                paddingRight: aiExplorer.show ? "10px" : "0"
            }}>
                <input type="file" id="fileUpload" multiple style={{ display: "none" }} onChange={(e) => handleUploadFiles(e, analysis?.folder?.id)} />
                <input type="file" id="folderUpload" webkitdirectory="true" style={{ display: "none" }} onChange={(e) => handleUploadFolder(e, analysis?.folder?.id)} />

                {!driveConnected ? (
                    <DriveLogin onConnect={handleConnect} />
                ) : (
                    <>
                        {!analysis ? (
                            <WorkspaceGrid 
                                rootFolders={rootFolders}
                                handleAnalyze={handleAnalyze}
                                setAiExplorer={setAiExplorer}
                                handleDelete={handleDelete}
                                handleDisconnect={async () => { await googleDriveApi.disconnectDrive(); setDriveConnected(false); }}
                                onUploadFile={() => document.getElementById('fileUpload').click()}
                                onUploadFolder={() => document.getElementById('folderUpload').click()}
                            />
                        ) : (
                            <WorkspaceFolderView 
                                analysis={analysis}
                                setAnalysis={setAnalysis}
                                setAiExplorer={setAiExplorer}
                                handleCreateFolder={handleCreateFolder}
                                handleCreateFile={handleCreateFile}
                                handleDelete={handleDelete}
                                handleAnalyze={handleAnalyze}
                                onUploadFile={() => document.getElementById('fileUpload').click()}
                            />
                        )}
                        <IntegrationModal 
                            {...modal} 
                            onChange={(value) => setModal({...modal, value})}
                            onCancel={closeModal} 
                            onConfirm={modal.onConfirm} 
                        />
                    </>
                )}
            </div>

            {aiExplorer.show && (
                <div className="ai-section" style={{ 
                    flex: "1 1 350px", 
                    minWidth: "350px", 
                    maxWidth: "500px",
                    height: "100%" 
                }}>
                    <FileExplorer
                        onClose={() => setAiExplorer({ show: false, folderName: "", folderId: null })}
                        folderName={aiExplorer.folderName}
                        folderId={aiExplorer.folderId}
                    />
                </div>
            )}
        </div>
        </>
    );
};

export default GoogleDriveManager;
