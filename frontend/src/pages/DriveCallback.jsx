import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { googleDriveApi } from "../services/googleDriveApi";

const DriveCallback = () => {
    const navigate = useNavigate();

    useEffect(() => {
        const handleCallback = async () => {
            const params = new URLSearchParams(window.location.search);
            const code = params.get("code");

            if (code) {
                try {
                    await googleDriveApi.connectDrive(code);
                    navigate("/integrations?success=true");
                } catch (err) {
                    console.error("Drive connection failed", err);
                    navigate("/integrations?error=failed");
                }
            } else {
                navigate("/integrations");
            }
        };

        handleCallback();
    }, [navigate]);

    return (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh", color: "white" }}>
            <div style={{ textAlign: "center" }}>
                <h2>Connecting Google Drive...</h2>
                <div className="loader"></div>
            </div>
        </div>
    );
};

export default DriveCallback;
