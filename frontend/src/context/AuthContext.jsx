import React, { createContext, useContext, useState, useEffect } from 'react';
import api from '../api';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchUser = async () => {
    try {
      const response = await api.get('/auth/users/me/');
      setUser(response.data);
    } catch (error) {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      fetchUser();
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (username, password) => {
    const response = await api.post('/auth/jwt/create/', { username, password });
    localStorage.setItem('access_token', response.data.access);
    localStorage.setItem('refresh_token', response.data.refresh);
    await fetchUser();
    return response.data;
  };

  const logout = () => {
    localStorage.clear();
    setUser(null);
  };

  const hasPermission = (perm) => {
    return user?.permissions?.includes(perm) || user?.is_superuser;
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading, hasPermission }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
