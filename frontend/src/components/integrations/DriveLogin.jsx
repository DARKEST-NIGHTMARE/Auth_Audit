import React from "react";
import buttonStyles from "../common/Button.module.css";

const DriveLogin = ({ onConnect }) => {
    return (
        <div style={{ textAlign: "center", padding: "50px" }}>
            <div style={{ fontSize: "4rem", marginBottom: "20px" }}>☁️</div>
            <h2>Connect Google Drive</h2>
            <p style={{ color: "#A0AEC0", marginBottom: "30px" }}>Link your Google account to analyze folders and files securely.</p>
            <button onClick={onConnect} className={`${buttonStyles.btn} ${buttonStyles.btnGoogle}`} style={{ width: "auto", padding: "12px 30px" }}>Login with Google</button>
        </div>
    );
};

export default DriveLogin;
