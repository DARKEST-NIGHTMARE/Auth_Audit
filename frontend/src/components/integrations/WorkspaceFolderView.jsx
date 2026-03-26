import React from "react";
import buttonStyles from "../common/Button.module.css";
import layoutStyles from "../common/Layout.module.css";

const WorkspaceFolderView = ({ 
    analysis, 
    setAnalysis, 
    setAiExplorer, 
    handleCreateFolder, 
    handleCreateFile, 
    handleDelete, 
    handleAnalyze,
    onUploadFile
}) => {
    return (
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
                        <button onClick={() => setAiExplorer({ show: true, folderName: analysis.folder.name, folderId: analysis.folder.id })} className={buttonStyles.btn} style={{ width: "auto", padding: "10px 18px", background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)", fontWeight: "bold" }}>🤖 AI Summarize</button>
                        <button onClick={() => handleCreateFolder(analysis.folder.id)} className={buttonStyles.btn} style={{ width: "auto", padding: "10px 18px", background: "#48bb78", fontWeight: "bold" }}>+ New Sub-Folder</button>
                        <button onClick={onUploadFile} className={buttonStyles.btn} style={{ width: "auto", padding: "10px 18px", background: "#4299e1", fontWeight: "bold" }}>⬆️ Upload File</button>
                        <button onClick={() => handleCreateFile(analysis.folder.id)} className={buttonStyles.btn} style={{ width: "auto", padding: "10px 18px", background: "rgba(255,255,255,0.1)", color: "white" }}>📝 New Document</button>
                    </div>
                </div>
                
                <div style={{ background: "rgba(0,0,0,0.2)", borderRadius: "10px", maxHeight: "400px", overflowY: "auto", overflowX: "hidden" }}>
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
                                    <div style={{ display: "flex", alignItems: "center", gap: "15px", flex: 1, minWidth: 0, paddingRight: "15px" }}>
                                        <span style={{ fontSize: "1.6rem", flexShrink: 0 }}>{file.mimeType.includes('folder') ? '📁' : '📄'}</span>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ color: "#F7FAFC", fontWeight: "600", fontSize: "1rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", textDecoration: file.mimeType.includes('folder') ? "underline rgba(102, 126, 234, 0.3)" : "none" }}>{file.name}</div>
                                            <div style={{ fontSize: "0.75rem", color: "#718096", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{file.mimeType.includes('folder') ? 'Sub-folder (Click to open)' : file.mimeType}</div>
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", alignItems: "center", gap: "20px", flexShrink: 0 }}>
                                        {file.size && <span style={{ color: "#718096", fontSize: "0.85rem", whiteSpace: "nowrap" }}>{parseInt(file.size) < 1024 * 1024 ? `${(parseInt(file.size)/1024).toFixed(1)} KB` : `${(parseInt(file.size)/(1024*1024)).toFixed(1)} MB`}</span>}
                                        <button onClick={(e) => { e.stopPropagation(); handleDelete(file.id, file.mimeType.includes('folder')); }} className={buttonStyles.btnDelete} style={{ padding: "5px", width: "36px", height: "36px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "8px" }} title="Move to trash">🗑️</button>
                                    </div>
                                </li>
                            ))
                        )}
                    </ul>
                </div>
            </div>
        </div>
    );
};

export default WorkspaceFolderView;
