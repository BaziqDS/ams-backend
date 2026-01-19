import React, { useState } from 'react';
import { X, Loader2, AlertCircle } from 'lucide-react';
import api from '../api';

const CategoryForm = ({ onClose, onRefresh, categories, initialData = null }) => {
  const [formData, setFormData] = useState({
    name: initialData?.name || '',
    parent_category: initialData?.parent_category || '',
    category_type: initialData?.category_type || '', 
    tracking_type: initialData?.tracking_type || '',
    default_depreciation_rate: initialData?.default_depreciation_rate || '',
    is_active: initialData?.is_active ?? true,
    notes: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isEdit = !!initialData;
  const isParent = !formData.parent_category;
  
  // Rate has changed logic
  const rateChanged = isEdit && parseFloat(formData.default_depreciation_rate) !== parseFloat(initialData?.default_depreciation_rate || 0);

  const parentCategory = categories.find(c => c.id === parseInt(formData.parent_category));
  const parentType = parentCategory?.resolved_category_type;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (rateChanged && !formData.notes) {
        setError('Please provide a justification (notes) for changing the depreciation rate.');
        return;
    }

    if (!isParent && formData.category_type === 'FIXED_ASSET' && parentType === 'CONSUMABLE') {
        setError('A Fixed Asset subcategory cannot be created under a Consumable parent category.');
        return;
    }

    setLoading(true);
    setError('');

    const submissionData = { ...formData };
    if (!submissionData.parent_category) {
        submissionData.parent_category = null;
        submissionData.tracking_type = null;
    } else {
        if (!submissionData.category_type) delete submissionData.category_type;
    }
    
    if (!submissionData.default_depreciation_rate) submissionData.default_depreciation_rate = null;

    try {
      if (isEdit) {
        await api.put(`/api/inventory/categories/${initialData.id}/`, submissionData);
      } else {
        await api.post('/api/inventory/categories/', submissionData);
      }
      onRefresh();
      onClose();
    } catch (err) {
      setError(err.response?.data ? JSON.stringify(err.response.data) : 'Failed to save category');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md">
      <div className="bg-slate-900 border border-white/10 w-full max-w-lg rounded-3xl p-8 shadow-2xl animate-in zoom-in duration-200">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h3 className="text-2xl font-bold">{isEdit ? 'Update Category' : 'Category Configuration'}</h3>
            <p className="text-xs text-slate-500 uppercase tracking-widest font-bold mt-1">
                {isParent ? 'Root Category' : 'Subcategory & tracking'}
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-full transition-colors">
            <X className="w-6 h-6 text-slate-400" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && <div className="text-red-400 bg-red-400/10 p-4 rounded-xl text-sm break-words border border-red-500/20">{error}</div>}
          
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
                <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Parent Category</label>
                <select
                disabled={isEdit}
                className="w-full bg-slate-800/50 border border-white/5 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 appearance-none text-sm disabled:opacity-50"
                value={formData.parent_category}
                onChange={(e) => setFormData({...formData, parent_category: e.target.value, category_type: '', tracking_type: '', default_depreciation_rate: ''})}
                >
                <option value="">-- NEW ROOT CATEGORY --</option>
                {categories.filter(c => !c.parent_category).map(cat => (
                    <option key={cat.id} value={cat.id}>{cat.name}</option>
                ))}
                </select>
            </div>

            <div className="col-span-2">
                <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Category Name *</label>
                <input
                type="text"
                className="w-full bg-slate-800/50 border border-white/5 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 text-sm"
                value={formData.name}
                onChange={(e) => setFormData({...formData, name: e.target.value})}
                required
                placeholder="e.g. IT Equipment, Furniture"
                />
            </div>
          </div>

          <div className="space-y-4 pt-4 border-t border-white/5">
            {isParent ? (
                <>
                    <div>
                        <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Category Type (Financial)</label>
                        <select
                            className="w-full bg-slate-800/50 border border-white/5 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 appearance-none text-sm"
                            value={formData.category_type}
                            onChange={(e) => setFormData({...formData, category_type: e.target.value})}
                            required
                        >
                            <option value="">Select Type...</option>
                            <option value="FIXED_ASSET">Fixed Asset (Depreciable)</option>
                            <option value="CONSUMABLE">Consumable (Expenseable)</option>
                        </select>
                    </div>

                    {(formData.category_type === 'FIXED_ASSET' || initialData?.resolved_category_type === 'FIXED_ASSET') && (
                        <div className="animate-in fade-in slide-in-from-top-2">
                            <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Depreciation Rate (%)</label>
                            <input
                                type="number"
                                step="0.01"
                                className="w-full bg-slate-800/50 border border-white/5 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500/50 text-sm"
                                value={formData.default_depreciation_rate}
                                onChange={(e) => setFormData({...formData, default_depreciation_rate: e.target.value})}
                                placeholder="10.00"
                                required
                            />
                        </div>
                    )}
                </>
            ) : (
                <>
                    <div>
                        <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Tracking Type (Operational)</label>
                        <div className="grid grid-cols-2 gap-2">
                            {['INDIVIDUAL', 'BATCH'].map(type => (
                                <button
                                    key={type}
                                    type="button"
                                    disabled={isEdit}
                                    onClick={() => setFormData({...formData, tracking_type: type})}
                                    className={`px-4 py-3 rounded-xl border text-xs font-bold transition-all ${formData.tracking_type === type ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-slate-800/50 border-white/5 text-slate-400 disabled:opacity-50 hover:bg-white/5'}`}
                                >
                                    {type}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="pt-2">
                        <p className="text-[9px] text-slate-500 italic">Financial overrides allow deviate behavior from parent settings.</p>
                        <button 
                            type="button"
                            onClick={() => setFormData({...formData, showOverride: !formData.showOverride})}
                            className="text-[10px] text-indigo-400 font-bold mt-2 hover:text-indigo-300"
                        >
                            {formData.showOverride ? '- Hide Overrides' : '+ Manage Financial Override'}
                        </button>
                    </div>

                    {(formData.showOverride || isEdit) && (
                         <div className="space-y-4 p-4 bg-white/5 rounded-2xl border border-white/5 animate-in slide-in-from-top-2">
                            <select
                                className="w-full bg-slate-900/50 border border-white/5 rounded-xl px-4 py-2 text-xs focus:outline-none"
                                value={formData.category_type}
                                onChange={(e) => setFormData({...formData, category_type: e.target.value})}
                            >
                                <option value="">Default (Inherit)</option>
                                <option value="FIXED_ASSET" disabled={parentType === 'CONSUMABLE'}>
                                    Fixed Asset {parentType === 'CONSUMABLE' && '(Disabled: Parent is Consumable)'}
                                </option>
                                <option value="CONSUMABLE">Consumable</option>
                            </select>
                            {(formData.category_type === 'FIXED_ASSET' || initialData?.resolved_category_type === 'FIXED_ASSET') && (
                                <input
                                    type="number"
                                    step="0.01"
                                    placeholder="Rate Override"
                                    className="w-full bg-slate-900/50 border border-white/5 rounded-xl px-4 py-2 text-xs focus:outline-none"
                                    value={formData.default_depreciation_rate}
                                    onChange={(e) => setFormData({...formData, default_depreciation_rate: e.target.value})}
                                />
                            )}
                         </div>
                    )}
                </>
            )}

            {rateChanged && (
                <div className="animate-in flash duration-500">
                    <label className="block text-[10px] font-bold text-amber-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                        <AlertCircle className="w-3 h-3" /> Justification for Rate Change *
                    </label>
                    <textarea
                        className="w-full bg-amber-500/5 border border-amber-500/20 rounded-xl px-4 py-3 focus:outline-none focus:ring-1 focus:ring-amber-500/50 text-xs text-amber-200 placeholder:text-amber-500/30"
                        rows="2"
                        value={formData.notes}
                        onChange={(e) => setFormData({...formData, notes: e.target.value})}
                        placeholder="Explain why the depreciation rate is being modified (for audit purposes)..."
                        required
                    />
                </div>
            )}
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-4 rounded-2xl transition-all flex items-center justify-center gap-2 shadow-xl shadow-indigo-900/20 active:scale-95 disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : (isEdit ? "Refine Configuration" : "Establish Category")}
          </button>
        </form>
      </div>
    </div>
  );
};

export default CategoryForm;
