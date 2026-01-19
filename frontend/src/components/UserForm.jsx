import React, { useState } from 'react';
import { X, Loader2, ShieldCheck } from 'lucide-react';
import api from '../api';

const UserForm = ({ onClose, onRefresh, locations }) => {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    re_password: '',
    first_name: '',
    last_name: '',
    employee_id: '',
    assigned_locations: [],
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLocationToggle = (locId) => {
    const newLocations = formData.assigned_locations.includes(locId)
      ? formData.assigned_locations.filter(id => id !== locId)
      : [...formData.assigned_locations, locId];
    setFormData({ ...formData, assigned_locations: newLocations });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (formData.password !== formData.re_password) {
      setError("Passwords do not match");
      return;
    }
    setLoading(true);
    setError('');

    try {
      await api.post('/auth/users/', formData);
      onRefresh();
      onClose();
    } catch (err) {
      setError(err.response?.data ? JSON.stringify(err.response.data) : 'Failed to create user');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm overflow-y-auto">
      <div className="bg-slate-900 border border-white/10 w-full max-w-2xl rounded-3xl p-8 shadow-2xl my-8">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-2xl font-bold flex items-center gap-3">
            <ShieldCheck className="text-blue-500" />
            Create New User
          </h3>
          <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-full transition-colors">
            <X className="w-6 h-6 text-slate-400" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="text-red-400 bg-red-400/10 p-4 rounded-xl text-sm break-words">{error}</div>}
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Username *</label>
              <input
                type="text"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                value={formData.username}
                onChange={(e) => setFormData({...formData, username: e.target.value})}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Email</label>
              <input
                type="email"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.email}
                onChange={(e) => setFormData({...formData, email: e.target.value})}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Password *</label>
              <input
                type="password"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.password}
                onChange={(e) => setFormData({...formData, password: e.target.value})}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Confirm Password *</label>
              <input
                type="password"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.re_password}
                onChange={(e) => setFormData({...formData, re_password: e.target.value})}
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">First Name</label>
              <input
                type="text"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.first_name}
                onChange={(e) => setFormData({...formData, first_name: e.target.value})}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Last Name</label>
              <input
                type="text"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.last_name}
                onChange={(e) => setFormData({...formData, last_name: e.target.value})}
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Employee ID</label>
            <input
              type="text"
              className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
              value={formData.employee_id}
              onChange={(e) => setFormData({...formData, employee_id: e.target.value})}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Assign Locations</label>
            <div className="grid grid-cols-2 gap-2 mt-2 max-h-32 overflow-y-auto p-2 bg-slate-800/50 rounded-xl border border-white/5">
              {locations.map(loc => (
                <label key={loc.id} className="flex items-center gap-2 cursor-pointer p-1 hover:bg-white/5 rounded transition-colors">
                  <input
                    type="checkbox"
                    checked={formData.assigned_locations.includes(loc.id)}
                    onChange={() => handleLocationToggle(loc.id)}
                  />
                  <span className="text-xs text-slate-300 truncate">{loc.name}</span>
                </label>
              ))}
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl transition-all flex items-center justify-center gap-2 mt-4"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Register User"}
          </button>
        </form>
      </div>
    </div>
  );
};

export default UserForm;
