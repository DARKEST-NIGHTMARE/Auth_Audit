import React from "react";
import buttonStyles from "../common/Button.module.css";
import layoutStyles from "../common/Layout.module.css";

const WorkspaceGrid = ({ 
    rootFolders, 
    handleAnalyze, 
    setAiExplorer, 
    handleDelete, 
    handleDisconnect, 
    onUploadFile, 
    onUploadFolder 
}) => {
    return (
        <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "30px", flexWrap: "wrap", gap: "15px", alignItems: "center" }}>
                <h3 style={{ margin: 0 }}>Your Audit Workspaces</h3>
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                    <button onClick={onUploadFile} className={buttonStyles.btn} style={{ padding: "10px 18px", width: "auto", background: "#4299e1", fontSize: "0.9rem", fontWeight: "bold" }}>📄 Upload File</button>
                    <button onClick={onUploadFolder} className={buttonStyles.btn} style={{ padding: "10px 18px", width: "auto", background: "#ed8936", fontSize: "0.9rem", fontWeight: "bold" }}>📂 Upload Folder</button>
                    <button onClick={handleDisconnect} className={buttonStyles.btnDelete} style={{ padding: "10px 18px", fontSize: "0.85rem", background: "transparent", border: "1px solid #e53e3e" }}>Disconnect</button>
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
                            <div style={{ position: "absolute", top: "15px", right: "15px", display: "flex", gap: "6px" }}>
                                <button onClick={(e) => { e.stopPropagation(); setAiExplorer({ show: true, folderName: folder.name, folderId: folder.id }); }} title="AI Summarize" style={{ padding: "0", width: "32px", height: "32px", fontSize: "0.9rem", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", background: "rgba(102,126,234,0.15)", border: "1px solid rgba(102,126,234,0.3)", color: "white", cursor: "pointer" }}>🤖</button>
                                <button onClick={(e) => { e.stopPropagation(); handleDelete(folder.id, true); }} className={buttonStyles.btnDelete} style={{ padding: "0", width: "32px", height: "32px", fontSize: "0.9rem", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", background: "rgba(229, 62, 62, 0.1)" }}>🗑️</button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default WorkspaceGrid;
