import React, { useState, useRef, useEffect } from 'react';
import { Link, useNavigate } from "react-router-dom";
import styles from "../Navbar.module.css";

const BACKEND_URL = process.env.REACT_APP_API_URL || 'http://localhost:8081';

const Navbar = ({ user, onLogout, activePage }) => {
    const [showDropdown, setShowDropdown] = useState(false);
    const dropdownRef = useRef(null);
    const navigate = useNavigate();

    const avatarSrc = (u) => {
        if (!u.avatar_url) return `https://ui-avatars.com/api/?name=${u.name}`;
        return u.avatar_url.startsWith("http")
            ? u.avatar_url
            : `${BACKEND_URL}${u.avatar_url}`;
    };

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
                setShowDropdown(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

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
                    {user.provider === 'clio' && (
                        <Link to="/clio" className={activePage === 'clio' ? styles.activeLink : ''}>
                            Clio
                        </Link>
                    )}
                </div>
            </div>

            <div className={styles.navRight} ref={dropdownRef}>
                <div 
                    className={styles.profileContainer} 
                    onClick={() => setShowDropdown(!showDropdown)}
                >
                    <div className={styles.userInfo}>
                        <span className={styles.userName}>{user.name}</span>
                        <span className={styles.userRole}>{user.role}</span>
                    </div>
                    <img src={avatarSrc(user)} className={styles.navAvatar} alt="profile" />
                    
                    {showDropdown && (
                        <div className={styles.profileDropdown}>
                            <div className={styles.dropdownHeader}>
                                <div className={styles.userName}>{user.name}</div>
                                <div className={styles.userRole} style={{fontSize: '0.7rem'}}>{user.email}</div>
                            </div>
                            
                            <Link to="/settings" className={styles.dropdownItem} onClick={() => setShowDropdown(false)}>
                                <span className={styles.dropdownIcon}>⚙️</span> Settings
                            </Link>
                            
                            <div className={styles.dropdownDivider} />
                            
                            <button 
                                onClick={() => {
                                    setShowDropdown(false);
                                    onLogout();
                                }} 
                                className={`${styles.dropdownItem} styles.logoutItem`}
                            >
                                <span className={styles.dropdownIcon}>🚪</span> Logout
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </nav>
    );
};
export default Navbar;