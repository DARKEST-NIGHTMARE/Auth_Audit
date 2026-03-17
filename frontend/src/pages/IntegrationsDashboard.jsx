import React, { useState, useEffect } from "react";
import { useSelector } from "react-redux";
import Navbar from "../components/Navbar";
import { googleDriveApi } from "../services/googleDriveApi";
import buttonStyles from "../components/common/Button.module.css";
import layoutStyles from "../components/common/Layout.module.css";
import formStyles from "../components/common/Form.module.css";
import styles from "./Dashboard.module.css"; // Reuse dashboard styles for consistency

const IntegrationsDashboard = () => {
    const { user } = useSelector((state) => state.auth);
    const [driveConnected, setDriveConnected] = useState(false);
    const [folders, setFolders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState("drive");
    const [analysis, setAnalysis] = useState(null);

    useEffect(() => {
        checkStatus();
    }, []);

    const checkStatus = async () => {
        try {
            const status = await googleDriveApi.getStatus();
            setDriveConnected(status.connected);
            if (status.connected) {
                fetchFolders();
            }
        } catch (err) {
            console.error("Failed to check Drive status", err);
        } finally {
            setLoading(false);
        }
    };

    const fetchFolders = async () => {
        try {
            const data = await googleDriveApi.getFolders();
            setFolders(data);
        } catch (err) {
            console.error("Failed to fetch folders", err);
        }
    };

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

    return (
        <div className={styles.dashboardContainer}>
            <Navbar user={user} activePage="integrations" />

            <div className={layoutStyles.glassCard}>
                <div style={{ display: "flex", gap: "20px", marginBottom: "30px", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                    <button 
                        onClick={() => setActiveTab("drive")}
                        className={`${buttonStyles.btn}`}
                        style={{ 
                            width: "auto", 
                            background: activeTab === "drive" ? "rgba(102, 126, 234, 0.2)" : "transparent",
                            border: "none",
                            color: activeTab === "drive" ? "#667eea" : "#718096",
                            padding: "10px 20px"
                        }}
                    >
                        Google Drive
                    </button>
                    {/* Placeholder for Clio if it returns */}
                    <button 
                        disabled
                        className={`${buttonStyles.btn}`}
                        style={{ 
                            width: "auto", 
                            background: "transparent",
                            border: "none",
                            color: "#4a5568",
                            padding: "10px 20px",
                            opacity: 0.5,
                            cursor: "not-allowed"
                        }}
                    >
                        Clio (Coming Soon)
                    </button>
                </div>

                {activeTab === "drive" && (
                    <div className="animate-fade-in">
                        {!driveConnected ? (
                            <div style={{ textAlign: "center", padding: "50px" }}>
                                <img src="/logo.svg" alt="Drive" style={{ width: "80px", opacity: 0.5, marginBottom: "20px" }} />
                                <h2>Connect Google Drive</h2>
                                <p style={{ color: "#718096", marginBottom: "30px" }}>
                                    Link your Google account to analyze folders and files securely.
                                </p>
                                <button 
                                    onClick={handleConnect}
                                    className={`${buttonStyles.btn} ${buttonStyles.btnGoogle}`}
                                    style={{ width: "auto", padding: "12px 30px" }}
                                >
                                    Login with Google
                                </button>
                            </div>
                        ) : (
                            <div>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "20px" }}>
                                    <h3>Your Drive Folders</h3>
                                    <button 
                                        onClick={async () => {
                                            await googleDriveApi.disconnectDrive();
                                            setDriveConnected(false);
                                        }}
                                        className={buttonStyles.btnDelete}
                                        style={{ padding: "5px 15px" }}
                                    >
                                        Disconnect
                                    </button>
                                </div>

                                {folders.length === 0 ? (
                                    <p style={{ color: "#718096" }}>No folders found in your App Folder.</p>
                                ) : (
                                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "20px" }}>
                                        {folders.map(folder => (
                                            <div 
                                                key={folder.id} 
                                                className={layoutStyles.glassCard}
                                                style={{ padding: "15px", cursor: "pointer", transition: "transform 0.2s" }}
                                                onClick={() => handleAnalyze(folder.id)}
                                            >
                                                <div style={{ fontSize: "2rem", marginBottom: "10px" }}>📁</div>
                                                <div style={{ fontWeight: "bold", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                    {folder.name}
                                                </div>
                                                <div style={{ fontSize: "0.8rem", color: "#718096" }}>
                                                    Modified: {new Date(folder.modifiedTime).toLocaleDateString()}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {analysis && (
                    <div className={layoutStyles.glassCard} style={{ marginTop: "30px", background: "rgba(0,0,0,0.2)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <h2>Analysis: {analysis.folder.name}</h2>
                            <button onClick={() => setAnalysis(null)} className={buttonStyles.btnDelete}>Close</button>
                        </div>
                        <div style={{ display: "flex", gap: "40px", marginTop: "20px" }}>
                            <div>
                                <div style={{ fontSize: "2rem", fontWeight: "bold", color: "#667eea" }}>
                                    {analysis.stats.total_files}
                                </div>
                                <div style={{ color: "#718096" }}>Total Files</div>
                            </div>
                            <div>
                                <div style={{ fontSize: "2rem", fontWeight: "bold", color: "#48bb78" }}>
                                    {(analysis.stats.total_size_bytes / 1024).toFixed(2)} KB
                                </div>
                                <div style={{ color: "#718096" }}>Total Size</div>
                            </div>
                        </div>
                        <div style={{ marginTop: "20px" }}>
                            <h4>File Types</h4>
                            <ul style={{ listStyle: "none", padding: 0 }}>
                                {Object.entries(analysis.stats.file_types_breakdown).map(([type, count]) => (
                                    <li key={type} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                                        <span style={{ fontSize: "0.9rem" }}>{type}</span>
                                        <span style={{ fontWeight: "bold" }}>{count}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default IntegrationsDashboard;
