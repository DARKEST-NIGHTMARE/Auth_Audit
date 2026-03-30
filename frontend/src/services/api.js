import axios from "axios";
// import { store } from "../redux/store"; 
import { logout } from "../redux/authSlice";

const API_URL = process.env.REACT_APP_API_URL;

const api = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
  withCredentials: true
});

let store;

export const injectStore = (_store) => {
  store = _store;
};

// req intceptor
api.interceptors.request.use((config) => {
  const token = store?.getState()?.auth?.token || localStorage.getItem("token");

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// res interceptor to handle 401 globally
let isRefreshing = false;
let refreshSubscribers = [];

const subscribeTokenRefresh = (cb) => {
  refreshSubscribers.push(cb);
};

const onRefreshed = (token) => {
  refreshSubscribers.map((cb) => cb(token));
  refreshSubscribers = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    const originalRequest = config;

    if (response && response.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve) => {
          subscribeTokenRefresh((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(api(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const res = await axios.post(`${API_URL}/api/auth/refresh`, {}, {
          withCredentials: true
        });

        const newToken = res.data.token;
        isRefreshing = false;
        
        localStorage.setItem("token", newToken);
        onRefreshed(newToken);
        
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      }
      catch (refreshError) {
        isRefreshing = false;
        refreshSubscribers = [];
        console.warn("Session expired. Logging out...");

        if (store) {
          store.dispatch(logout());
        } else {
          localStorage.removeItem("token");
          window.location.href = "/";
        }

        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  }
);

export default api;