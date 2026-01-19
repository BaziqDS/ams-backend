import React, { useState } from 'react';
import { X, Loader2 } from 'lucide-react';
import api from '../api';

const LocationForm = ({ onClose, onRefresh, locations }) => {
  const [formData, setFormData] = useState({
    name: '',
    parent_location: '',
    location_type: 'SITE',
    is_store: false,
    is_standalone: false,
    is_main_store: false,
    description: '',
    address: '',
    in_charge: '',
    contact_number: '',
    is_active: true,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    
    // Clean up empty strings for FKs
    const submissionData = { ...formData };
    if (!submissionData.parent_location) submissionData.parent_location = null;
    
    try {
      await api.post('/api/inventory/locations/', submissionData);
      onRefresh();
      onClose();
    } catch (err) {
      setError(err.response?.data ? JSON.stringify(err.response.data) : 'Failed to create location');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm overflow-y-auto">
      <div className="bg-slate-900 border border-white/10 w-full max-w-2xl rounded-3xl p-8 shadow-2xl my-8">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-2xl font-bold">Add New Location</h3>
          <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-full transition-colors">
            <X className="w-6 h-6 text-slate-400" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <div className="text-red-400 bg-red-400/10 p-4 rounded-xl text-sm break-words">{error}</div>}
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Name *</label>
              <input
                type="text"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                value={formData.name}
                onChange={(e) => setFormData({...formData, name: e.target.value})}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Parent Location</label>
              <select
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.parent_location}
                onChange={(e) => setFormData({...formData, parent_location: e.target.value})}
              >
                <option value="">-- No Parent (Root) --</option>
                {locations.filter(l => l.is_standalone).map(loc => (
                  <option key={loc.id} value={loc.id}>{loc.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Type *</label>
              <select
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.location_type}
                onChange={(e) => setFormData({...formData, location_type: e.target.value})}
              >
                <option value="DEPARTMENT">Department</option>
                <option value="BUILDING">Building</option>
                <option value="STORE">Store</option>
                <option value="ROOM">Room</option>
                <option value="LAB">Lab</option>
                <option value="OFFICE">Office</option>
                <option value="OTHER">Other</option>
              </select>
            </div>
            <div>
               <label className="block text-sm font-medium text-slate-400 mb-1">In Charge</label>
               <input
                type="text"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.in_charge}
                onChange={(e) => setFormData({...formData, in_charge: e.target.value})}
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 py-2">
            <label className="flex items-center gap-2 cursor-pointer bg-slate-800/50 p-3 rounded-xl border border-white/5">
              <input
                type="checkbox"
                checked={formData.is_standalone}
                onChange={(e) => setFormData({...formData, is_standalone: e.target.checked})}
              />
              <span className="text-xs text-slate-300">Standalone?</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer bg-slate-800/50 p-3 rounded-xl border border-white/5">
              <input
                type="checkbox"
                checked={formData.is_store}
                onChange={(e) => setFormData({...formData, is_store: e.target.checked, is_main_store: e.target.checked ? formData.is_main_store : false})}
              />
              <span className="text-xs text-slate-300">Is Store?</span>
            </label>
            {formData.is_store && (
              <label className="flex items-center gap-2 cursor-pointer bg-slate-800/50 p-3 rounded-xl border border-white/5">
                <input
                  type="checkbox"
                  checked={formData.is_main_store}
                  onChange={(e) => setFormData({...formData, is_main_store: e.target.checked})}
                />
                <span className="text-xs text-slate-300">Main Store?</span>
              </label>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Contact Number</label>
              <input
                type="text"
                className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2.5 focus:outline-none"
                value={formData.contact_number}
                onChange={(e) => setFormData({...formData, contact_number: e.target.value})}
              />
            </div>
            <div className="flex items-center h-full pt-6">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.is_active}
                  onChange={(e) => setFormData({...formData, is_active: e.target.checked})}
                />
                <span className="text-sm text-slate-300">Active</span>
              </label>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Description</label>
            <textarea
              className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2 focus:outline-none h-16"
              value={formData.description}
              onChange={(e) => setFormData({...formData, description: e.target.value})}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1">Address</label>
            <textarea
              className="w-full bg-slate-800 border border-white/5 rounded-xl px-4 py-2 focus:outline-none h-16"
              value={formData.address}
              onChange={(e) => setFormData({...formData, address: e.target.value})}
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl transition-all flex items-center justify-center gap-2 mt-2"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : "Create Location"}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LocationForm;
