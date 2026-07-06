import React, { useState, useEffect } from "react";
import { useSelector } from "react-redux";
import { formatDistanceToNow } from "date-fns";
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from "recharts";

import { securityApi } from "../services/securityApi";
import SecurityMap from "../components/security/SecurityMap";
import buttonStyles from "../components/common/Button.module.css";
import layoutStyles from "../components/common/Layout.module.css";
import employeeTableStyles from "../components/EmployeeTable.module.css";
import styles from "./SecurityDashboard.module.css";

const SecurityDashboard = () => {
    const { user } = useSelector((state) => state.auth);

    // const [events, setEvents] = useState([]);
    const [logs, setLogs] = useState([]);
    const [alerts, setAlerts] = useState([]);
    const [activeUsers, setActiveUsers] = useState([]);
    const [mySessions, setMySessions] = useState([]);

    const [tableLoading, setTableLoading] = useState(true);
    const [error, setError] = useState(null);

    const [eventTypeFilter, setEventTypeFilter] = useState("");
    const [page, setPage] = useState(0);
    const limit = 10;

    useEffect(() => {
        const fetchStaticWidgets = async () => {
            try {
                if (user?.role === "ADMIN") {
                    const usersData = await securityApi.getActiveUsers(7);
                    setActiveUsers(usersData);

                    const [suspicious, locked] = await Promise.all([
                        securityApi.getEvents(0, 10, "SUSPICIOUS_ACTIVITY"),
                        securityApi.getEvents(0, 10, "ACCOUNT_LOCKED")
                    ]);

                    const combinedAlerts = [...suspicious, ...locked]
                        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
                        .slice(0, 10);

                    setAlerts(combinedAlerts);
                } else {
                    const sessionData = await securityApi.getOwnSessions();
                    setMySessions(sessionData);
                }
            } catch (err) {
                console.error("Failed to load top widgets:", err);
            }
        };

        if (user) {
            fetchStaticWidgets();
        }
    }, [user]);

    useEffect(() => {
        const fetchTableLogs = async () => {
            setTableLoading(true);
            setError(null);
            try {
                let logsData;
                if (user?.role === "ADMIN") {
                    if (eventTypeFilter === "ACTIVE_USER_SESSION") {
                        logsData = await securityApi.getAllSessions();
                        // mock log structure so table code works
                        logsData = logsData.map(s => ({
                            id: s.id,
                            created_at: s.last_active,
                            event_type: "ACTIVE_USER_SESSION",
                            username: s.user_name,
                            user_email: s.user_email,
                            user_id: s.user_id,
                            ip_address: s.ip_address,
                            event_metadata: {
                                device: s.device_info,
                                location: s.location,
                                is_active: s.is_active
                            },
                            is_session: true
                        }));
                    } else {
                        logsData = await securityApi.getEvents(page * limit, limit, eventTypeFilter);
                    }
                } else {
                    logsData = await securityApi.getOwnEvents(page * limit, limit, eventTypeFilter);
                }
                setLogs(logsData);
            } catch (err) {
                setError(err.response?.data?.detail || "Failed to load audit logs.");
            } finally {
                setTableLoading(false);
            }
        };

        if (user) {
            fetchTableLogs();
        }
    }, [page, eventTypeFilter, user]);

    useEffect(() => {
        // Role stored as uppercase "ADMIN" in the database
        if (!user || user.role !== "ADMIN") return;

        const token = localStorage.getItem("token");
        if (!token) return;

        const backendUrl = process.env.REACT_APP_API_URL || "http://localhost:8081";
        // Browser WebSockets cannot send custom headers, so we pass the JWT
        // as a query parameter — the backend reads it from ?token=
        const wsUrl = backendUrl.replace(/^http/, "ws") +
            `/api/admin/security/ws?token=${encodeURIComponent(token)}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.debug("[SecurityWS] Connected to live security feed.");
        };

        ws.onerror = (err) => {
            console.warn("[SecurityWS] Connection error:", err);
        };

        ws.onmessage = (event) => {
            try {
                const newEvent = JSON.parse(event.data);
                // Skip error/rejection messages from the server
                if (newEvent.error) {
                    console.warn("[SecurityWS] Server rejected connection:", newEvent.error);
                    ws.close();
                    return;
                }
                if (newEvent.event_type === "SUSPICIOUS_ACTIVITY" || newEvent.event_type === "ACCOUNT_LOCKED") {
                    setAlerts(prevAlerts => [newEvent, ...prevAlerts].slice(0, 10));
                }
                setLogs(prevLogs => {
                    if (eventTypeFilter && newEvent.event_type !== eventTypeFilter) {
                        return prevLogs;
                    }
                    return [newEvent, ...prevLogs].slice(0, limit);
                });
            } catch (e) {
                console.warn("[SecurityWS] Failed to parse message:", e);
            }
        };

        return () => {
            if (ws.readyState === WebSocket.OPEN) ws.close();
        };
    }, [eventTypeFilter, limit, user]);

    const getEventBadgeClass = (type) => {
        switch (type) {
            case "FAILED_LOGIN": return buttonStyles.badgeFailed;
            case "SUSPICIOUS_ACTIVITY": return buttonStyles.badgeSuspicious;
            case "ACCOUNT_LOCKED": return buttonStyles.badgeLocked;
            case "ACTIVE_SESSION": return buttonStyles.badgeActive;
            default: return buttonStyles.badgeDefault;
        }
    };

    const handleRevokeSession = async (sessionId) => {
        if (!window.confirm("Are you sure you want to log out this device?")) return;
        try {
            await securityApi.revokeSession(sessionId);
            setMySessions(mySessions.filter(s => s.id !== sessionId));
        } catch (err) {
            alert("Failed to revoke session");
        }
    };

    const handleAdminRevokeSession = async (sessionId) => {
        if (!window.confirm("Are you sure you want to log out this user's device?")) return;
        try {
            await securityApi.adminRevokeSession(sessionId);
            // Updating the logs state to remove revoked session visually
            setLogs(logs.filter(log => log.id !== sessionId || !log.is_session));
        } catch (err) {
            alert("Failed to revoke session");
        }
    };

    if (!user) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: '50px' }}>
                <h3>Loading Profile...</h3>
            </div>
        );
    }

    return (
            <div className={layoutStyles.glassCard}>
                <div className={styles.securityHeader}>
                    <h1>Security Center</h1>
                </div>

                {error ? (
                    <div className={styles.textCenterMuted} style={{ color: '#e53e3e' }}>Error: {error}</div>
                ) : (
                    <>
                        <div className={styles.securityGrid}>
                            {user?.role === "ADMIN" ? (
                                <>
                                    <div className={styles.dashboardCard}>
                                        <h2 style={{ color: '#c53030' }}> Alerts</h2>
                                        <div className={styles.alertList}>
                                            {alerts.length === 0 ? (
                                                <p className={styles.textCenterMuted}>No active alerts detected.</p>
                                            ) : (
                                                alerts.map(alert => (
                                                    <div key={alert.id} className={styles.alertItem}>
                                                        <strong>
                                                            {alert.username || "Unknown User"} (ID: {alert.user_id || 'N/A'})
                                                        </strong>
                                                        {' '}triggered {alert.event_type.replace("_", " ")}
                                                        <div className={styles.alertMeta}>
                                                            Reason: {alert.event_metadata?.reason || "Anomaly detected"}
                                                            <br />
                                                            Time: {formatDistanceToNow(new Date(alert.created_at), { addSuffix: true })}
                                                        </div>
                                                    </div>
                                                ))
                                            )}
                                        </div>
                                    </div>

                                    <div className={styles.dashboardCard}>
                                        <h2>Recent User Logins (7 Days)</h2>
                                        <div style={{ width: '100%', height: '250px', minWidth: 0 }}>
                                            {activeUsers.length === 0 ? (
                                                <div className={styles.textCenterMuted}>No activity data available</div>
                                            ) : (
                                                <ResponsiveContainer width="99%" height="100%">
                                                    <BarChart data={activeUsers.slice(0, 5)} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                                                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                                                        <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#718096', fontSize: 12 }} />
                                                        <YAxis axisLine={false} tickLine={false} tick={{ fill: '#718096', fontSize: 12 }} />
                                                        <Tooltip cursor={{ fill: '#edf2f7' }} contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }} />
                                                        <Bar dataKey="total_logins" fill="#667eea" radius={[4, 4, 0, 0]} name="Total Logins" />
                                                    </BarChart>
                                                </ResponsiveContainer>
                                            )}
                                        </div>
                                    </div>
                                </>
                            ) : (
                                <>
                                    <div className={styles.dashboardCard} style={{ gridColumn: '1 / -1' }}>
                                        <h2>Your Active Devices</h2>
                                        <div className={layoutStyles.tableWrapper}>
                                            <table className={employeeTableStyles.empTable}>
                                                <thead>
                                                    <tr>
                                                        <th>Device</th>
                                                        <th>Location</th>
                                                        <th>Last Active</th>
                                                        <th>Action</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {mySessions.length === 0 ? (
                                                        <tr><td colSpan="4" className={styles.textCenterMuted}>No active sessions found.</td></tr>
                                                    ) : (
                                                        mySessions.map((session) => (
                                                            <tr key={session.id}>
                                                                <td style={{ fontWeight: '600', color: '#2d3748' }}>
                                                                    {session.device_info || 'Unknown Device'}
                                                                    <div style={{ fontSize: '0.8rem', color: '#718096', fontFamily: 'monospace' }}>
                                                                        IP: {session.ip_address}
                                                                    </div>
                                                                </td>
                                                                <td style={{ color: '#4a5568' }}>
                                                                    📍 {session.location || 'Unknown'}
                                                                </td>
                                                                <td style={{ color: '#718096', fontSize: '0.9rem' }}>
                                                                    {formatDistanceToNow(new Date(session.last_active), { addSuffix: true })}
                                                                </td>
                                                                <td>
                                                                    <button
                                                                        onClick={() => handleRevokeSession(session.id)}
                                                                        className={buttonStyles.btnDelete}
                                                                    >
                                                                        Revoke Session
                                                                    </button>
                                                                </td>
                                                            </tr>
                                                        ))
                                                    )}
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                </>
                            )}

                            <div className={styles.dashboardCard} style={{ gridColumn: user?.role === 'ADMIN' ? 'auto' : '1 / -1' }}>
                                <h2>Live Security Map</h2>
                                <div style={{ width: '100%', height: '250px', minWidth: 0, position: 'relative' }}>
                                    <SecurityMap events={logs} />
                                </div>
                            </div>
                        </div>

                        <div className={styles.dashboardCard}>
                            <div className={styles.tableHeaderFlex}>
                                <h2 style={{ border: 'none', margin: 0, padding: 0 }}>
                                    {user?.role === "ADMIN" ? "All Logs" : "Your Logs"}
                                    {tableLoading && <span style={{ fontSize: '0.8rem', color: '#718096', marginLeft: '10px' }}>Updating...</span>}
                                </h2>

                                <select
                                    className={styles.filterSelect}
                                    value={eventTypeFilter}
                                    onChange={(e) => { setEventTypeFilter(e.target.value); setPage(0); }}
                                >
                                    <option value="">All Events</option>
                                    <option value="FAILED_LOGIN">Failed Logins</option>
                                    <option value="ACTIVE_SESSION">Successful Logins</option>
                                    {user?.role === "ADMIN" && (
                                        <option value="ACTIVE_USER_SESSION">Active User Sessions</option>
                                    )}
                                    <option value="SUSPICIOUS_ACTIVITY">Suspicious Activity</option>
                                    <option value="ACCOUNT_LOCKED">Account Lockouts</option>
                                </select>
                            </div>

                            <div className={layoutStyles.tableWrapper}>
                                <table className={employeeTableStyles.empTable}>
                                    <thead>
                                        <tr>
                                            <th>Time</th>
                                            <th>Event</th>
                                            {user?.role === "ADMIN" && <th>User</th>}
                                            <th>IP Address</th>
                                            <th>Details</th>
                                            {user?.role === "ADMIN" && eventTypeFilter === "ACTIVE_USER_SESSION" && <th>Action</th>}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {tableLoading ? (
                                            <tr>
                                                <td colSpan={user?.role === "ADMIN" ? (eventTypeFilter === "ACTIVE_USER_SESSION" ? "6" : "5") : "4"} className={styles.textCenterMuted}>Filtering Logs...</td>
                                            </tr>
                                        ) : logs.length === 0 ? (
                                            <tr>
                                                <td colSpan={user?.role === "ADMIN" ? (eventTypeFilter === "ACTIVE_USER_SESSION" ? "6" : "5") : "4"} className={styles.textCenterMuted}>No events found matching your criteria.</td>
                                            </tr>
                                        ) : (
                                            logs.map((log) => (
                                                <tr key={log.id}>
                                                    <td style={{ color: '#718096', fontSize: '0.9rem' }}>
                                                        {formatDistanceToNow(new Date(log.created_at), { addSuffix: true })}
                                                    </td>
                                                    <td>
                                                        <span className={`${buttonStyles.badge} ${getEventBadgeClass(log.event_type)}`}>
                                                            {log.event_type}
                                                        </span>
                                                    </td>
                                                    {user?.role === "ADMIN" && (
                                                        <td style={{ fontWeight: '600', color: '#2d3748' }}>
                                                            {log.username || `Unknown (ID: ${log.user_id || 'N/A'})`}
                                                        </td>
                                                    )}
                                                    <td style={{ color: '#718096', fontFamily: 'monospace' }}>
                                                        {log.ip_address || 'N/A'}
                                                        {log.event_metadata?.location && (
                                                            <div style={{ fontSize: '0.75rem', color: '#4a5568', marginTop: '4px', fontFamily: 'Inter, sans-serif' }}>
                                                                📍 {log.event_metadata.location}
                                                            </div>
                                                        )}
                                                    </td>
                                                    <td style={{ color: '#718096', fontSize: '0.8rem', maxWidth: '200px' }}>
                                                        {log.event_metadata ? JSON.stringify(log.event_metadata).replace(/[{}]/g, '').replace(/"/g, '') : ''}
                                                        {log.user_email && <div style={{ marginTop: '4px' }}>{log.user_email}</div>}
                                                    </td>
                                                    {user?.role === "ADMIN" && eventTypeFilter === "ACTIVE_USER_SESSION" && (
                                                        <td>
                                                            <button
                                                                onClick={() => handleAdminRevokeSession(log.id)}
                                                                className={buttonStyles.btnDelete}
                                                            >
                                                                Revoke Session
                                                            </button>
                                                        </td>
                                                    )}
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                </table>
                            </div>

                            <div className="pagination">
                                <button
                                    disabled={page === 0}
                                    onClick={() => setPage(p => Math.max(0, p - 1))}
                                    className={`${buttonStyles.btn} ${buttonStyles.btnGoogle}`}
                                    style={{ width: 'auto', padding: '6px 16px', margin: 0 }}
                                >
                                    Previous
                                </button>
                                <span style={{ color: '#718096', alignSelf: 'center', fontSize: '0.9rem' }}>Page {page + 1}</span>
                                <button
                                    disabled={logs.length < limit || eventTypeFilter === "ACTIVE_USER_SESSION"}
                                    onClick={() => setPage(p => p + 1)}
                                    className={`${buttonStyles.btn} ${buttonStyles.btnGoogle}`}
                                    style={{ width: 'auto', padding: '6px 16px', margin: 0 }}
                                >
                                    Next
                                </button>
                            </div>
                        </div>
                    </>
                )}
            </div>
    );
};

export default SecurityDashboard;