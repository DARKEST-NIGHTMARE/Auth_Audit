import React, { useState } from "react";
import GoogleDriveManager from "../components/integrations/GoogleDriveManager";
import layoutStyles from "../components/common/Layout.module.css";
import buttonStyles from "../components/common/Button.module.css";

const IntegrationsDashboard = () => {
    const [activeTab, setActiveTab] = useState("drive");

    return (
        <div className={layoutStyles.container}>
            <div className={layoutStyles.header}>
                <h1 className={layoutStyles.title}>External Integrations</h1>
                <p className={layoutStyles.subtitle}>
                    Manage and sync data from third-party services for your audit activities.
                </p>
            </div>

            <div className={layoutStyles.glassCard} style={{ position: "relative" }}>
                {/* Tab Navigation */}
                <div style={{ display: "flex", gap: "20px", marginBottom: "30px", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                    <button 
                        onClick={() => setActiveTab("drive")}
                        className={`${buttonStyles.btn}`}
                        style={{ 
                            width: "auto", 
                            background: activeTab === "drive" ? "rgba(102, 126, 234, 0.2)" : "transparent",
                            border: "none",
                            color: activeTab === "drive" ? "#667eea" : "#F7FAFC",
                            padding: "10px 20px"
                        }}
                    >
                        Google Drive
                    </button>
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

                {/* Integration Manager */}
                {activeTab === "drive" && <GoogleDriveManager />}
                
                {activeTab === "clio" && (
                    <div style={{ textAlign: "center", padding: "50px", color: "#A0AEC0" }}>
                        <h3>Clio Integration Is Coming Soon</h3>
                        <p>We are working hard to bring you legal practice management integration.</p>
                    </div>
                )}
            </div>
        </div>
    );
};

export default IntegrationsDashboard;
