import React from "react";
import layoutStyles from "./Layout.module.css";

const IntegrationModal = ({ show, title, type, value, placeholder, confirmText, onCancel, onConfirm, onChange }) => {
    if (!show) return null;

    return (
        <div style={{
            position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: "rgba(0,0,0,0.8)", backdropFilter: "blur(8px)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
            animation: "fadeIn 0.2s ease"
        }}>
            <div className={layoutStyles.glassCard} style={{
                width: "100%", maxWidth: "400px", padding: "30px",
                border: "1px solid rgba(255,255,255,0.1)", background: "rgba(26, 32, 44, 0.95)"
            }}>
                <h3 style={{ marginTop: 0, marginBottom: "20px", color: "#F7FAFC" }}>{title}</h3>
                
                {type === "input" && (
                    <input 
                        type="text"
                        className={layoutStyles.glassCard}
                        style={{
                            width: "100%", padding: "12px", marginBottom: "25px",
                            background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
                            color: "white", outline: "none"
                        }}
                        placeholder={placeholder}
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                        autoFocus
                    />
                )}
                
                {type === "confirm" && (
                    <p style={{ color: "#A0AEC0", marginBottom: "25px", fontSize: "1rem" }}>
                        This action will move the selected item to your Google Drive trash. You can restore it from there later.
                    </p>
                )}

                <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
                    <button 
                        onClick={onCancel}
                        style={{ 
                            padding: "10px 20px", background: "transparent", border: "1px solid rgba(255,255,255,0.2)",
                            color: "white", borderRadius: "8px", cursor: "pointer"
                        }}
                    >
                        Cancel
                    </button>
                    <button 
                        onClick={() => onConfirm(value)}
                        style={{ 
                            padding: "10px 20px", background: type === "confirm" ? "#e53e3e" : "#667eea",
                            border: "none", color: "white", borderRadius: "8px", cursor: "pointer", fontWeight: "bold"
                        }}
                    >
                        {confirmText}
                    </button>
                </div>
                <style>
                    {`
                    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
                    `}
                </style>
            </div>
        </div>
    );
};

export default IntegrationModal;
