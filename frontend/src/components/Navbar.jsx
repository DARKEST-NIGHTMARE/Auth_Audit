import React from 'react';
import { Link } from "react-router-dom";
import styles from "./Navbar.module.css";

const BACKEND_URL = process.env.REACT_APP_API_URL;

const Navbar = ({ user, onLogout, activePage }) => {
    const avatarSrc = (u) => {
        if (!u.avatar_url) return `https://ui-avatars.com/api/?name=${u.name}`;
        return u.avatar_url.startsWith("http")
            ? u.avatar_url
            : `${BACKEND_URL}${u.avatar_url}`;
    };

    return (
        <nav className={styles.navbar}>
            <div className={styles.navLeft}>
                <h3 className={styles.brand}>Portal</h3>

                <div className={styles.navLinks}>
                    <Link to="/dashboard" className={activePage === 'dashboard' ? styles.activeLink : ''}>
                        Employees
                    </Link>
                    {user.role === 'ADMIN' && (
                        <Link to="/users" className={activePage === 'users' ? styles.activeLink : ''}>
                            Users
                        </Link>
                    )}
                    <Link to="/security" className={activePage === 'security' ? styles.activeLink : ''}>
                        Security
                    </Link>
                    <Link to="/integrations" className={activePage === 'integrations' ? styles.activeLink : ''}>
                        Integrations
                    </Link>
                </div>
            </div>

            <div className={styles.navRight}>
                <div className={styles.userInfo}>
                    <span className={styles.userName}>{user.name}</span>
                    <span className={styles.userRole}>{user.role}</span>
                </div>

                <img src={avatarSrc(user)} className={styles.navAvatar} alt="profile" />

                <button onClick={onLogout} className={styles.btnLogout}>
                    Logout
                </button>
            </div>
        </nav>
    );
};
export default Navbar;