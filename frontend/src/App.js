import React, { useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { fetchUser } from "./redux/authSlice";
import "./assets/App.css";
import PrivateRoute from "./utils/PrivateRoute";
import AuthCallback from "./pages/AuthCallback";
import SecurityDashboard from "./pages/SecurityDashboard";
import ErrorBoundary from "./components/ErrorBoundary";

const Login = React.lazy(() => import("./pages/Login"));
const Dashboard = React.lazy(() => import("./pages/Dashboard"));
const Users = React.lazy(() => import("./pages/Users"));
const IntegrationsDashboard = React.lazy(() => import("./pages/IntegrationsDashboard"));
const DriveCallback = React.lazy(() => import("./pages/DriveCallback"));
const NotFound = React.lazy(() => import("./pages/NotFound"));

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
      <Router>
        <ErrorBoundary>
          <React.Suspense fallback={<div>Loading...</div>}>
            <Routes>
              <Route path="/" element={!user ? <Login /> : <Navigate to="/dashboard" />} />
              <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
              <Route path="/users" element={<PrivateRoute><Users /></PrivateRoute>} />
              <Route path="/integrations" element={<PrivateRoute><IntegrationsDashboard /></PrivateRoute>} />
              <Route path="/drive/callback" element={<DriveCallback />} />
              <Route path="/security" element={<PrivateRoute><SecurityDashboard /></PrivateRoute>} />
              <Route path="/auth/callback" element={<AuthCallback />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </React.Suspense>
        </ErrorBoundary>
      </Router>
    </div>
  );
}

export default App;