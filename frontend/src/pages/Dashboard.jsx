import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api';
import { 
  LayoutDashboard, MapPin, Tags, LogOut, Plus, 
  Building2, Shovel, ShieldCheck, AlertCircle 
} from 'lucide-react';
import LocationForm from '../components/LocationForm';
import CategoryForm from '../components/CategoryForm';
import UserForm from '../components/UserForm';

const Dashboard = () => {
  const { user, logout, hasPermission } = useAuth();
  const [locations, setLocations] = useState([]);
  const [categories, setCategories] = useState([]);
  const [users, setUsers] = useState([]);
  const [activeTab, setActiveTab] = useState('locations');
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState(null);
  
  // Historical Lookups
  const [historicalDate, setHistoricalDate] = useState('');
  const [historicalRates, setHistoricalRates] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  const canAddLocation = hasPermission('inventory.add_location');
  const canAddCategory = hasPermission('inventory.add_category');
  const canAddUser = hasPermission('auth.add_user');
  
  const canAdd = 
    activeTab === 'locations' ? canAddLocation : 
    activeTab === 'categories' ? canAddCategory : 
    canAddUser;

  const fetchData = async () => {
    setLoading(true);
    try {
      const endpoints = [
        api.get('/api/inventory/locations/'),
        api.get('/api/inventory/categories/')
      ];
      
      if (hasPermission('auth.view_user')) {
        endpoints.push(api.get('/auth/users/'));
      }

      const results = await Promise.allSettled(endpoints);
      
      if (results[0].status === 'fulfilled') setLocations(results[0].value.data);
      if (results[1].status === 'fulfilled') setCategories(results[1].value.data);

      if (results[2] && results[2].status === 'fulfilled') {
        setUsers(results[2].value.data);
      }
      
    } catch (err) {
      console.error('Major failure in fetchData');
    } finally {
      setLoading(false);
    }
  };

  const fetchHistoricalRates = async (date) => {
    if (!date) {
        setHistoricalRates(null);
        return;
    }
    setHistoryLoading(true);
    try {
        const res = await api.get(`/api/inventory/categories/historical_rates/?date=${date}`);
        setHistoricalRates(res.data);
    } catch (err) {
        console.error('Failed to fetch historical rates');
    } finally {
        setHistoryLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
      if (activeTab !== 'categories') {
          setHistoricalDate('');
          setHistoricalRates(null);
      }
  }, [activeTab]);

  return (
    <div className="flex h-screen bg-slate-950 overflow-hidden text-slate-200">
      {/* Sidebar */}
      <div className="w-64 bg-slate-900/50 border-r border-white/5 flex flex-col p-6">
        <div className="flex items-center gap-3 mb-10 px-2">
          <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center font-bold text-xl text-white">A</div>
          <span className="font-bold text-xl text-white">AMS v5</span>
        </div>

        <nav className="flex-1 space-y-2">
          {[
            { id: 'locations', label: 'Locations', icon: MapPin },
            { id: 'categories', label: 'Categories', icon: Tags },
          ].map((tab) => (
            <button 
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${activeTab === tab.id ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20' : 'text-slate-400 hover:text-white hover:bg-white/5'}`}
            >
              <tab.icon className="w-5 h-5" />
              <span>{tab.label}</span>
            </button>
          ))}
          
          {hasPermission('auth.view_user') && (
            <button 
              onClick={() => setActiveTab('users')}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${activeTab === 'users' ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/20' : 'text-slate-400 hover:text-white hover:bg-white/5'}`}
            >
              <LayoutDashboard className="w-5 h-5" />
              <span>Users</span>
            </button>
          )}
        </nav>

        <div className="pt-6 border-t border-white/5 mt-auto">
          <div className="flex items-center gap-3 px-2 mb-4">
            <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-xs text-white">
              {user?.username?.[0]?.toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate text-white">{user?.username}</p>
              <p className="text-xs text-slate-500 truncate">{user?.email}</p>
            </div>
          </div>
          <button 
            onClick={logout}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-red-400 hover:bg-red-400/10 transition-all"
          >
            <LogOut className="w-5 h-5" />
            <span>Logout</span>
          </button>
        </div>
      </div>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto p-10 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-indigo-950/20 via-transparent to-transparent">
        <div className="max-w-6xl mx-auto">
          <header className="flex items-center justify-between mb-10">
            <div>
              <h2 className="text-3xl font-bold capitalize text-white">{activeTab}</h2>
              <p className="text-slate-400 mt-1">Manage your university assets and logistics</p>
            </div>
            <div className="flex items-center gap-4">
              {activeTab === 'categories' && (
                  <div className="flex items-center gap-2 bg-slate-900/50 border border-white/5 px-4 py-2 rounded-xl">
                      <span className="text-[10px] uppercase font-bold text-slate-500">Financial Time Machine</span>
                      <input 
                        type="date" 
                        className="bg-transparent border-none text-xs focus:ring-0 text-indigo-400 font-bold p-0"
                        value={historicalDate}
                        onChange={(e) => {
                            setHistoricalDate(e.target.value);
                            fetchHistoricalRates(e.target.value);
                        }}
                      />
                  </div>
              )}
              {canAdd && (
                <button 
                  onClick={() => {
                      setEditingCategory(null);
                      setShowModal(true);
                  }}
                  className="bg-white text-slate-900 hover:bg-slate-200 px-6 py-2.5 rounded-xl font-semibold transition-all flex items-center gap-2 shadow-lg"
                >
                  <Plus className="w-5 h-5" />
                  Add {activeTab.slice(0, -1)}
                </button>
              )}
            </div>
          </header>

          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-pulse">
              {[1, 2, 3, 4, 5, 6].map(i => (
                <div key={i} className="h-48 bg-slate-900 rounded-3xl border border-white/5" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {activeTab === 'locations' ? (
                locations.map(loc => (
                  <div key={loc.id} className="bg-slate-900/50 backdrop-blur-sm p-6 rounded-3xl border border-white/5 hover:border-blue-500/50 transition-all group">
                    <div className="flex items-start justify-between mb-4">
                      <div className="w-12 h-12 bg-blue-600/10 text-blue-400 rounded-2xl flex items-center justify-center">
                        <Building2 className="w-6 h-6" />
                      </div>
                      <span className={`px-3 py-1 rounded-full text-[10px] font-bold tracking-wider uppercase ${loc.is_store ? 'bg-amber-500/10 text-amber-500' : 'bg-green-500/10 text-green-500'}`}>
                        {loc.location_type}
                      </span>
                    </div>
                    <h3 className="font-bold text-lg mb-1 group-hover:text-blue-400 transition-colors text-white">{loc.name}</h3>
                    <p className="text-slate-500 text-sm font-mono uppercase">{loc.code}</p>
                    {loc.is_standalone && (
                      <div className="mt-4 pt-4 border-t border-white/5 flex gap-2">
                        <span className="bg-indigo-500/10 text-indigo-400 text-[10px] px-2 py-0.5 rounded-md uppercase font-bold">Standalone</span>
                        {loc.is_main_store && <span className="bg-blue-500/10 text-blue-400 text-[10px] px-2 py-0.5 rounded-md uppercase font-bold">Main Store</span>}
                      </div>
                    )}
                  </div>
                ))
              ) : activeTab === 'categories' ? (
                categories.map(cat => {
                    const historicalData = historicalRates?.find(r => r.id === cat.id);
                    return (
                        <div key={cat.id} className="bg-slate-900/50 backdrop-blur-sm p-6 rounded-3xl border border-white/5 hover:border-indigo-500/50 transition-all group relative overflow-hidden">
                            {historicalDate && (
                                <div className="absolute top-0 right-0 left-0 bg-indigo-500/90 text-white text-[9px] font-bold py-1 px-3 flex justify-between uppercase">
                                    <span>Historical View: {historicalDate}</span>
                                    <span>Rate: {historicalData?.effective_rate}%</span>
                                </div>
                            )}
                            <div className="flex items-start justify-between mb-4">
                            <div className="w-12 h-12 bg-indigo-600/10 text-indigo-400 rounded-2xl flex items-center justify-center">
                                <Tags className="w-6 h-6" />
                            </div>
                            <div className="flex gap-2">
                                {hasPermission('inventory.change_category') && (
                                    <button 
                                        onClick={() => {
                                            setEditingCategory(cat);
                                            setShowModal(true);
                                        }}
                                        className="p-2 bg-slate-800 text-slate-400 hover:text-white rounded-lg transition-colors"
                                    >
                                        <Plus className="w-4 h-4 rotate-45" /> {/* Just using Plus as a placeholder for edit pencil if needed */}
                                    </button>
                                )}
                                <span className="bg-slate-800 text-slate-400 px-3 py-1 rounded-full text-[10px] font-bold tracking-wider uppercase">
                                    {cat.resolved_category_type?.replace('_', ' ')}
                                </span>
                            </div>
                            </div>
                            <h3 className="font-bold text-lg mb-1 group-hover:text-indigo-400 transition-colors text-white">{cat.name}</h3>
                            <p className="text-slate-500 text-sm font-mono uppercase">{cat.code}</p>
                            <div className="mt-4 pt-4 border-t border-white/5 flex flex-wrap gap-2">
                            {cat.resolved_tracking_type && <span className="text-[10px] text-slate-500 uppercase font-bold tracking-widest">Track: {cat.resolved_tracking_type?.replace('_', ' ')}</span>}
                            {cat.resolved_category_type === 'FIXED_ASSET' && (
                                <span className="text-[10px] text-amber-500 uppercase font-bold tracking-widest bg-amber-500/10 px-2 py-0.5 rounded-md">
                                    Rate: {cat.resolved_depreciation_rate}%
                                </span>
                            )}
                            </div>

                            {cat.rate_history?.length > 0 && (
                                <div className="mt-4 pt-4 border-t border-white/5">
                                    <button 
                                        onClick={() => setCategories(categories.map(c => c.id === cat.id ? {...c, showHistory: !c.showHistory} : c))}
                                        className="text-[9px] text-slate-500 uppercase font-bold hover:text-indigo-400 transition-colors"
                                    >
                                        {cat.showHistory ? 'Hide Audit Trail' : 'Show Financial Audit Trail'}
                                    </button>
                                    
                                    {cat.showHistory && (
                                        <div className="space-y-3 mt-4 animate-in slide-in-from-top-2">
                                            {cat.rate_history.map((h, idx) => (
                                                <div key={idx} className="flex gap-3 relative">
                                                    {idx !== cat.rate_history.length - 1 && <div className="absolute left-[5px] top-3 bottom-0 w-[1px] bg-slate-800" />}
                                                    <div className="w-2.5 h-2.5 rounded-full bg-blue-500/40 border border-blue-500/60 mt-0.5 z-10" />
                                                    <div className="flex-1 min-w-0">
                                                        <div className="flex justify-between items-center mb-0.5">
                                                            <span className="text-[10px] font-bold text-slate-300">{h.rate}%</span>
                                                            <span className="text-[8px] text-slate-600">{new Date(h.changed_at).toLocaleDateString()}</span>
                                                        </div>
                                                        <p className="text-[9px] text-slate-500 line-clamp-1 italic">{h.notes}</p>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })
              ) : (
                users.map(u => (
                  <div key={u.id} className="bg-slate-900/50 backdrop-blur-sm p-6 rounded-3xl border border-white/5 hover:border-emerald-500/50 transition-all group">
                    <div className="flex items-start justify-between mb-4">
                      <div className="w-12 h-12 bg-emerald-600/10 text-emerald-400 rounded-2xl flex items-center justify-center font-bold text-xl text-white">
                        {u.username[0].toUpperCase()}
                      </div>
                      <span className="bg-slate-800 text-slate-400 px-3 py-1 rounded-full text-[10px] font-bold tracking-wider uppercase">
                        {u.is_superuser ? 'Admin' : 'User'}
                      </span>
                    </div>
                    <h3 className="font-bold text-lg mb-1 group-hover:text-emerald-400 transition-colors text-white">{u.username}</h3>
                    <p className="text-slate-500 text-sm truncate">{u.email || 'No email'}</p>
                    <div className="mt-4 pt-4 border-t border-white/5">
                      <p className="text-[10px] text-slate-500 uppercase font-bold tracking-widest">Permissions: {u.permissions.length}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </main>

      {showModal && activeTab === 'locations' && (
        <LocationForm 
          onClose={() => setShowModal(false)} 
          onRefresh={fetchData} 
          locations={locations}
        />
      )}
      {showModal && activeTab === 'categories' && (
        <CategoryForm 
          onClose={() => {
              setShowModal(false);
              setEditingCategory(null);
          }} 
          onRefresh={fetchData} 
          categories={categories}
          initialData={editingCategory}
        />
      )}
      {showModal && activeTab === 'users' && (
        <UserForm 
          onClose={() => setShowModal(false)} 
          onRefresh={fetchData} 
          locations={locations}
        />
      )}
    </div>
  );
};

export default Dashboard;
