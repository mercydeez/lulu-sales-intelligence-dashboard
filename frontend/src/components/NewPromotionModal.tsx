'use client';

import React, { useState, useEffect } from 'react';
import { X, Tag, Calendar, Percent, DollarSign, Store, Package, AlertCircle } from 'lucide-react';

interface NewPromotionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

interface FormData {
  name: string;
  description: string;
  discount_type: 'percentage' | 'fixed' | 'bogo';
  discount_value: number;
  start_date: string;
  end_date: string;
  min_purchase: number;
  max_discount: number;
  category: string;
  store_ids: number[];
}

const CATEGORIES = [
  'Dairy', 'Fruits', 'Vegetables', 'Meat', 'Beverages', 
  'Bakery', 'Frozen Foods', 'Household', 'Personal Care', 'Snacks'
];

const STORES = [
  { id: 1, name: 'Lulu Hypermarket Al Barsha' },
  { id: 2, name: 'Lulu Hypermarket Deira City Centre' },
  { id: 3, name: 'Lulu Hypermarket Karama' },
  { id: 4, name: 'Lulu Hypermarket Mushrif Mall' },
  { id: 5, name: 'Lulu Hypermarket Al Wahda' },
  { id: 6, name: 'Lulu Hypermarket Khalidiyah' },
  { id: 7, name: 'Lulu Hypermarket Sharjah City Centre' },
  { id: 8, name: 'Lulu Hypermarket Al Nahda' },
  { id: 9, name: 'Lulu Express Marina' },
  { id: 10, name: 'Lulu Express JLT' },
];

export default function NewPromotionModal({ isOpen, onClose, onSuccess, authFetch }: NewPromotionModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(1);
  
  const [formData, setFormData] = useState<FormData>({
    name: '',
    description: '',
    discount_type: 'percentage',
    discount_value: 10,
    start_date: new Date().toISOString().split('T')[0],
    end_date: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    min_purchase: 0,
    max_discount: 0,
    category: '',
    store_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], // All stores by default
  });

  useEffect(() => {
    if (isOpen) {
      setStep(1);
      setError(null);
      // Reset form with default dates
      setFormData({
        name: '',
        description: '',
        discount_type: 'percentage',
        discount_value: 10,
        start_date: new Date().toISOString().split('T')[0],
        end_date: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
        min_purchase: 0,
        max_discount: 0,
        category: '',
        store_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      });
    }
  }, [isOpen]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: name === 'discount_value' || name === 'min_purchase' || name === 'max_discount' 
        ? parseFloat(value) || 0 
        : value
    }));
  };

  const handleStoreToggle = (storeId: number) => {
    setFormData(prev => ({
      ...prev,
      store_ids: prev.store_ids.includes(storeId)
        ? prev.store_ids.filter(id => id !== storeId)
        : [...prev.store_ids, storeId]
    }));
  };

  const handleSelectAllStores = () => {
    setFormData(prev => ({
      ...prev,
      store_ids: prev.store_ids.length === STORES.length ? [] : STORES.map(s => s.id)
    }));
  };

  const validateStep = (currentStep: number): boolean => {
    setError(null);
    
    if (currentStep === 1) {
      if (!formData.name.trim()) {
        setError('Promotion name is required');
        return false;
      }
      if (!formData.description.trim()) {
        setError('Description is required');
        return false;
      }
    }
    
    if (currentStep === 2) {
      if (formData.discount_value <= 0) {
        setError('Discount value must be greater than 0');
        return false;
      }
      if (formData.discount_type === 'percentage' && formData.discount_value > 100) {
        setError('Percentage discount cannot exceed 100%');
        return false;
      }
    }
    
    if (currentStep === 3) {
      if (new Date(formData.end_date) <= new Date(formData.start_date)) {
        setError('End date must be after start date');
        return false;
      }
      if (formData.store_ids.length === 0) {
        setError('Select at least one store');
        return false;
      }
    }
    
    return true;
  };

  const handleNext = () => {
    if (validateStep(step)) {
      setStep(prev => Math.min(prev + 1, 3));
    }
  };

  const handleBack = () => {
    setStep(prev => Math.max(prev - 1, 1));
  };

  const handleSubmit = async () => {
    if (!validateStep(3)) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const response = await authFetch('/api/promotions/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      
      if (response.ok) {
        await response.json();
        onSuccess();
        onClose();
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to create promotion');
      }
    } catch (err) {
      console.error('Error creating promotion:', err);
      setError('Network error. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const getDiscountPreview = () => {
    switch (formData.discount_type) {
      case 'percentage':
        return `${formData.discount_value}% OFF`;
      case 'fixed':
        return `AED ${formData.discount_value} OFF`;
      case 'bogo':
        return 'BUY 1 GET 1 FREE';
      default:
        return '';
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      
      {/* Modal */}
      <div className="relative bg-gray-900 rounded-2xl shadow-2xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-hidden border border-gray-700 z-[10000]">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-600/20 rounded-lg">
              <Tag className="w-6 h-6 text-red-500" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">Create New Promotion</h2>
              <p className="text-sm text-gray-400">Step {step} of 3</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>
        
        {/* Progress Bar */}
        <div className="px-6 pt-4">
          <div className="flex gap-2">
            {[1, 2, 3].map(s => (
              <div 
                key={s}
                className={`h-1 flex-1 rounded-full transition-colors ${
                  s <= step ? 'bg-red-600' : 'bg-gray-700'
                }`}
              />
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[60vh]">
          {error && (
            <div className="mb-4 p-3 bg-red-900/30 border border-red-700 rounded-lg flex items-center gap-2 text-red-400">
              <AlertCircle className="w-5 h-5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Step 1: Basic Info */}
          {step === 1 && (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold text-white mb-4">Basic Information</h3>
              
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Promotion Name *
                </label>
                <input
                  type="text"
                  name="name"
                  value={formData.name}
                  onChange={handleInputChange}
                  placeholder="e.g., Weekend Special - Dairy Products"
                  className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:border-red-500 focus:ring-1 focus:ring-red-500"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Description *
                </label>
                <textarea
                  name="description"
                  value={formData.description}
                  onChange={handleInputChange}
                  rows={3}
                  placeholder="Describe the promotion offer..."
                  className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:border-red-500 focus:ring-1 focus:ring-red-500"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Category (Optional)
                </label>
                <select
                  name="category"
                  value={formData.category}
                  onChange={handleInputChange}
                  className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-red-500 focus:ring-1 focus:ring-red-500"
                >
                  <option value="">All Categories</option>
                  {CATEGORIES.map(cat => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Step 2: Discount Details */}
          {step === 2 && (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold text-white mb-4">Discount Details</h3>
              
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Discount Type
                </label>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { value: 'percentage', label: 'Percentage', icon: Percent },
                    { value: 'fixed', label: 'Fixed Amount', icon: DollarSign },
                    { value: 'bogo', label: 'Buy 1 Get 1', icon: Package },
                  ].map(type => (
                    <button
                      key={type.value}
                      type="button"
                      onClick={() => setFormData(prev => ({ ...prev, discount_type: type.value as any }))}
                      className={`p-4 rounded-lg border-2 transition-colors flex flex-col items-center gap-2 ${
                        formData.discount_type === type.value
                          ? 'border-red-500 bg-red-900/20'
                          : 'border-gray-600 hover:border-gray-500'
                      }`}
                    >
                      <type.icon className={`w-6 h-6 ${formData.discount_type === type.value ? 'text-red-500' : 'text-gray-400'}`} />
                      <span className={`text-sm ${formData.discount_type === type.value ? 'text-white' : 'text-gray-400'}`}>
                        {type.label}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
              
              {formData.discount_type !== 'bogo' && (
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Discount Value {formData.discount_type === 'percentage' ? '(%)' : '(AED)'}
                  </label>
                  <input
                    type="number"
                    name="discount_value"
                    value={formData.discount_value}
                    onChange={handleInputChange}
                    min="1"
                    max={formData.discount_type === 'percentage' ? 100 : 10000}
                    className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-red-500 focus:ring-1 focus:ring-red-500"
                  />
                </div>
              )}
              
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Minimum Purchase (AED)
                  </label>
                  <input
                    type="number"
                    name="min_purchase"
                    value={formData.min_purchase}
                    onChange={handleInputChange}
                    min="0"
                    placeholder="0"
                    className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-red-500 focus:ring-1 focus:ring-red-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Max Discount (AED)
                  </label>
                  <input
                    type="number"
                    name="max_discount"
                    value={formData.max_discount}
                    onChange={handleInputChange}
                    min="0"
                    placeholder="No limit"
                    className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-red-500 focus:ring-1 focus:ring-red-500"
                  />
                </div>
              </div>

              {/* Preview */}
              <div className="mt-6 p-4 bg-gradient-to-r from-red-600 to-red-700 rounded-xl">
                <p className="text-sm text-red-200 mb-1">Preview</p>
                <p className="text-3xl font-bold text-white">{getDiscountPreview()}</p>
                {formData.min_purchase > 0 && (
                  <p className="text-sm text-red-200 mt-1">
                    On purchases above AED {formData.min_purchase}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Step 3: Schedule & Stores */}
          {step === 3 && (
            <div className="space-y-4">
              <h3 className="text-lg font-semibold text-white mb-4">Schedule & Stores</h3>
              
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    <Calendar className="w-4 h-4 inline mr-1" />
                    Start Date
                  </label>
                  <input
                    type="date"
                    name="start_date"
                    value={formData.start_date}
                    onChange={handleInputChange}
                    className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-red-500 focus:ring-1 focus:ring-red-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    <Calendar className="w-4 h-4 inline mr-1" />
                    End Date
                  </label>
                  <input
                    type="date"
                    name="end_date"
                    value={formData.end_date}
                    onChange={handleInputChange}
                    className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-red-500 focus:ring-1 focus:ring-red-500"
                  />
                </div>
              </div>
              
              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="block text-sm font-medium text-gray-300">
                    <Store className="w-4 h-4 inline mr-1" />
                    Select Stores
                  </label>
                  <button
                    type="button"
                    onClick={handleSelectAllStores}
                    className="text-sm text-red-500 hover:text-red-400"
                  >
                    {formData.store_ids.length === STORES.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto">
                  {STORES.map(store => (
                    <label
                      key={store.id}
                      className={`flex items-center p-3 rounded-lg border cursor-pointer transition-colors ${
                        formData.store_ids.includes(store.id)
                          ? 'border-red-500 bg-red-900/20'
                          : 'border-gray-600 hover:border-gray-500'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={formData.store_ids.includes(store.id)}
                        onChange={() => handleStoreToggle(store.id)}
                        className="sr-only"
                      />
                      <div className={`w-4 h-4 rounded border mr-3 flex items-center justify-center ${
                        formData.store_ids.includes(store.id) 
                          ? 'bg-red-600 border-red-600' 
                          : 'border-gray-500'
                      }`}>
                        {formData.store_ids.includes(store.id) && (
                          <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        )}
                      </div>
                      <span className={`text-sm ${formData.store_ids.includes(store.id) ? 'text-white' : 'text-gray-400'}`}>
                        {store.name}
                      </span>
                    </label>
                  ))}
                </div>
                <p className="text-sm text-gray-500 mt-2">
                  {formData.store_ids.length} store(s) selected
                </p>
              </div>

              {/* Summary Preview */}
              <div className="mt-4 p-4 bg-gray-800 rounded-xl border border-gray-700">
                <h4 className="text-sm font-medium text-gray-300 mb-3">Promotion Summary</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Name:</span>
                    <span className="text-white font-medium">{formData.name || '-'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Discount:</span>
                    <span className="text-red-500 font-bold">{getDiscountPreview()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Duration:</span>
                    <span className="text-white">
                      {new Date(formData.start_date).toLocaleDateString()} - {new Date(formData.end_date).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Category:</span>
                    <span className="text-white">{formData.category || 'All Categories'}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-6 border-t border-gray-700 bg-gray-800/50">
          <button
            onClick={step === 1 ? onClose : handleBack}
            className="px-6 py-2 text-gray-400 hover:text-white transition-colors"
          >
            {step === 1 ? 'Cancel' : 'Back'}
          </button>
          
          {step < 3 ? (
            <button
              onClick={handleNext}
              className="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
            >
              Next
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Creating...
                </>
              ) : (
                'Create Promotion'
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
