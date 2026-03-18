import React, { useState, useEffect, useCallback, useMemo } from "react";
import { googleDriveApi } from "../../services/googleDriveApi";
import IntegrationModal from "../common/IntegrationModal";
import buttonStyles from "../common/Button.module.css";
import layoutStyles from "../common/Layout.module.css";

const GoogleDriveManager = () => {
    const [driveConnected, setDriveConnected] = useState(false);
    const [folders, setFolders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [analysis, setAnalysis] = useState(null);
    const [modal, setModal] = useState({ show: false, title: "", type: "input", value: "", confirmText: "OK", onConfirm: null, placeholder: "" });

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
        <div className="animate-fade-in">
            <input type="file" id="fileUpload" multiple style={{ display: "none" }} onChange={(e) => handleUploadFiles(e, analysis?.folder?.id)} />
            <input type="file" id="folderUpload" webkitdirectory="true" style={{ display: "none" }} onChange={(e) => handleUploadFolder(e, analysis?.folder?.id)} />

            {!driveConnected ? (
                <div style={{ textAlign: "center", padding: "50px" }}>
                    <div style={{ fontSize: "4rem", marginBottom: "20px" }}>☁️</div>
                    <h2>Connect Google Drive</h2>
                    <p style={{ color: "#A0AEC0", marginBottom: "30px" }}>Link your Google account to analyze folders and files securely.</p>
                    <button onClick={handleConnect} className={`${buttonStyles.btn} ${buttonStyles.btnGoogle}`} style={{ width: "auto", padding: "12px 30px" }}>Login with Google</button>
                </div>
            ) : (
                <>
                    {!analysis ? (
                        <div>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "30px", flexWrap: "wrap", gap: "15px", alignItems: "center" }}>
                                <h3 style={{ margin: 0 }}>Your Audit Workspaces</h3>
                                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                                    <button onClick={() => document.getElementById('fileUpload').click()} className={buttonStyles.btn} style={{ padding: "10px 18px", width: "auto", background: "#4299e1", fontSize: "0.9rem", fontWeight: "bold" }}>📄 Upload File</button>
                                    <button onClick={() => document.getElementById('folderUpload').click()} className={buttonStyles.btn} style={{ padding: "10px 18px", width: "auto", background: "#ed8936", fontSize: "0.9rem", fontWeight: "bold" }}>📂 Upload Folder</button>
                                    <button onClick={async () => { await googleDriveApi.disconnectDrive(); setDriveConnected(false); }} className={buttonStyles.btnDelete} style={{ padding: "10px 18px", fontSize: "0.85rem", background: "transparent", border: "1px solid #e53e3e" }}>Disconnect</button>
                                </div>
                            </div>

                            {rootFolders.length === 0 ? (
                                <div style={{ textAlign: "center", padding: "40px", background: "rgba(255,255,255,0.02)", borderRadius: "16px", border: "1px dashed rgba(255,255,255,0.1)" }}>
                                    <p style={{ color: "#A0AEC0", fontSize: "1.1rem" }}>No root workspaces found.</p>
                                    <p style={{ color: "#718096", fontSize: "0.9rem" }}>Upload a file or folder to get started with your audit.</p>
                                </div>
                            ) : (
                                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: "25px" }}>
                                    {rootFolders.map(folder => (
                                        <div key={folder.id} className={layoutStyles.glassCard} style={{ padding: "24px", position: "relative", background: "rgba(255,255,255,0.05)", transition: "all 0.3s ease", border: "1px solid rgba(255,255,255,0.08)" }}>
                                            <div onClick={() => handleAnalyze(folder.id)} style={{ cursor: "pointer" }}>
                                                <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "15px" }}>
                                                    <div style={{ fontSize: "2.8rem" }}>📁</div>
                                                    <span style={{ fontSize: "0.65rem", background: "#667eea", padding: "4px 10px", borderRadius: "12px", color: "white", fontWeight: "bold", textTransform: "uppercase" }}>Root Workspace</span>
                                                </div>
                                                <div style={{ fontWeight: "bold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#F7FAFC", fontSize: "1.1rem" }}>{folder.name}</div>
                                                <div style={{ fontSize: "0.8rem", color: "#A0AEC0", marginTop: "6px" }}>Modified: {new Date(folder.modifiedTime).toLocaleDateString()}</div>
                                            </div>
                                            <button onClick={(e) => { e.stopPropagation(); handleDelete(folder.id, true); }} className={buttonStyles.btnDelete} style={{ position: "absolute", top: "15px", right: "15px", padding: "0", width: "32px", height: "32px", fontSize: "0.9rem", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", background: "rgba(229, 62, 62, 0.1)" }}>🗑️</button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className={layoutStyles.glassCard} style={{ background: "rgba(0,0,0,0.4)", border: "1px solid rgba(102, 126, 234, 0.4)", backdropFilter: "blur(10px)" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
                                <div>
                                    <span style={{ fontSize: "0.8rem", color: "#667eea", fontWeight: "bold", textTransform: "uppercase" }}>Current Workspace</span>
                                    <h2 style={{ margin: 0, fontSize: "1.8rem", color: "#F7FAFC" }}>📁 {analysis.folder.name}</h2>
                                </div>
                                <button onClick={() => setAnalysis(null)} className={buttonStyles.btnDelete} style={{ padding: "8px 20px" }}>← Back to Drive</button>
                            </div>
                            
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px", marginBottom: "30px" }}>
                                <div style={{ background: "rgba(255,255,255,0.05)", padding: "20px", borderRadius: "12px" }}>
                                    <div style={{ fontSize: "2.2rem", fontWeight: "bold", color: "#667eea" }}>{analysis.stats.total_files}</div>
                                    <div style={{ color: "#A0AEC0", fontSize: "0.9rem" }}>Files & Folders Found</div>
                                </div>
                                <div style={{ background: "rgba(255,255,255,0.05)", padding: "20px", borderRadius: "12px" }}>
                                    <div style={{ fontSize: "2.2rem", fontWeight: "bold", color: "#48bb78" }}>
                                        {analysis.stats.total_size_bytes < 1024 * 1024 
                                            ? `${(analysis.stats.total_size_bytes / 1024).toFixed(1)} KB`
                                            : `${(analysis.stats.total_size_bytes / (1024 * 1024)).toFixed(1)} MB`}
                                    </div>
                                    <div style={{ color: "#A0AEC0", fontSize: "0.9rem" }}>Total Workspace Size</div>
                                </div>
                            </div>
                            
                            <div style={{ marginTop: "40px", borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: "30px" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "25px", flexWrap: "wrap", gap: "15px" }}>
                                    <h3 style={{ margin: 0, color: "#E2E8F0" }}>Manage Content in "{analysis.folder.name}"</h3>
                                    <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                                        <button onClick={() => handleCreateFolder(analysis.folder.id)} className={buttonStyles.btn} style={{ width: "auto", padding: "10px 18px", background: "#48bb78", fontWeight: "bold" }}>+ New Sub-Folder</button>
                                        <button onClick={() => document.getElementById('fileUpload').click()} className={buttonStyles.btn} style={{ width: "auto", padding: "10px 18px", background: "#4299e1", fontWeight: "bold" }}>⬆️ Upload File</button>
                                        <button onClick={() => handleCreateFile(analysis.folder.id)} className={buttonStyles.btn} style={{ width: "auto", padding: "10px 18px", background: "rgba(255,255,255,0.1)", color: "white" }}>📝 New Document</button>
                                    </div>
                                </div>
                                
                                <div style={{ background: "rgba(0,0,0,0.2)", borderRadius: "10px", overflow: "hidden" }}>
                                    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                                        {analysis.files.length === 0 ? (
                                            <li style={{ padding: "40px", textAlign: "center", color: "#718096" }}>This folder is empty. Use the buttons above to add content.</li>
                                        ) : (
                                            analysis.files.map(file => (
                                                <li key={file.id} 
                                                    onClick={() => file.mimeType.includes('folder') ? handleAnalyze(file.id) : null}
                                                    style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,0.05)", transition: "background 0.2s", cursor: file.mimeType.includes('folder') ? "pointer" : "default" }}
                                                    className="file-list-item"
                                                    onMouseOver={(e) => { if(file.mimeType.includes('folder')) e.currentTarget.style.background = "rgba(102, 126, 234, 0.05)"; }}
                                                    onMouseOut={(e) => { e.currentTarget.style.background = "transparent"; }}
                                                >
                                                    <div style={{ display: "flex", alignItems: "center", gap: "15px" }}>
                                                        <span style={{ fontSize: "1.6rem" }}>{file.mimeType.includes('folder') ? '📁' : '📄'}</span>
                                                        <div>
                                                            <div style={{ color: "#F7FAFC", fontWeight: "600", fontSize: "1rem", textDecoration: file.mimeType.includes('folder') ? "underline rgba(102, 126, 234, 0.3)" : "none" }}>{file.name}</div>
                                                            <div style={{ fontSize: "0.75rem", color: "#718096" }}>{file.mimeType.includes('folder') ? 'Sub-folder (Click to open)' : file.mimeType}</div>
                                                        </div>
                                                    </div>
                                                    <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
                                                        {file.size && <span style={{ color: "#718096", fontSize: "0.85rem" }}>{parseInt(file.size) < 1024 * 1024 ? `${(parseInt(file.size)/1024).toFixed(1)} KB` : `${(parseInt(file.size)/(1024*1024)).toFixed(1)} MB`}</span>}
                                                        <button onClick={(e) => { e.stopPropagation(); handleDelete(file.id, file.mimeType.includes('folder')); }} className={buttonStyles.btnDelete} style={{ padding: "5px", width: "36px", height: "36px", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "8px" }} title="Move to trash">🗑️</button>
                                                    </div>
                                                </li>
                                            ))
                                        )}
                                    </ul>
                                </div>
                            </div>
                        </div>
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
    );
};

export default GoogleDriveManager;
