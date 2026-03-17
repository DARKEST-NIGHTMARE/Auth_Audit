import React, { useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { fetchUser } from "./redux/authSlice";
import "./assets/App.css";
import PrivateRoute from "./utils/PrivateRoute";
import AuthCallback from "./pages/AuthCallback";
import SecurityDashboard from "./pages/SecurityDashboard";
import ErrorBoundary from "./components/ErrorBoundary";
import WaterRipple from "./components/common/WaterRipple";
import MainLayout from "./components/layout/MainLayout";

const Login = React.lazy(() => import("./pages/Login"));
const Dashboard = React.lazy(() => import("./pages/Dashboard"));
const Users = React.lazy(() => import("./pages/Users"));
const ClioDashboard = React.lazy(() => import("./pages/ClioDashboard"));
const ProfileSettings = React.lazy(() => import("./pages/ProfileSettings"));
const IntegrationsDashboard = React.lazy(() => import("./pages/IntegrationsDashboard"));
const DriveCallback = React.lazy(() => import("./pages/DriveCallback"));

function App() {
  const dispatch = useDispatch();
  const { token, user } = useSelector((state) => state.auth);

  useEffect(() => {
    if (token) {
      dispatch(fetchUser());
    }
  }, [token, dispatch]);

  return (
    <div className={`app-container ${user ? "logged-in" : ""}`}>
      <WaterRipple />
      <Router>
        <ErrorBoundary>
          <React.Suspense fallback={<div>Loading...</div>}>
            <Routes>
              <Route path="/" element={!user ? <Login /> : <Navigate to="/dashboard" />} />
              <Route path="/dashboard" element={<PrivateRoute><MainLayout activePage="dashboard"><Dashboard /></MainLayout></PrivateRoute>} />
              <Route path="/users" element={<PrivateRoute><MainLayout activePage="users"><Users /></MainLayout></PrivateRoute>} />
              <Route path="/security" element={<PrivateRoute><MainLayout activePage="security"><SecurityDashboard /></MainLayout></PrivateRoute>} />
              <Route path="/clio" element={<PrivateRoute><MainLayout activePage="clio"><ClioDashboard /></MainLayout></PrivateRoute>} />
              <Route path="/integrations" element={<PrivateRoute><MainLayout activePage="integrations"><IntegrationsDashboard /></MainLayout></PrivateRoute>} />
              <Route path="/drive/callback" element={<DriveCallback />} />
              <Route path="/settings" element={<PrivateRoute><MainLayout activePage="settings"><ProfileSettings /></MainLayout></PrivateRoute>} />
              <Route path="/auth/callback" element={<AuthCallback />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </React.Suspense>
        </ErrorBoundary>
      </Router>
    </div>
  );
}

export default App;