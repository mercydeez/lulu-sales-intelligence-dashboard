'use client';

import React, { useState } from 'react';
import { X, User, Mail, Phone, Building, Briefcase, Calendar, Globe, AlertCircle, Loader2, CheckCircle } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface NewEmployeeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const STORES = [
  { id: 1, name: 'Lulu Hypermarket Al Barsha', location: 'Dubai' },
  { id: 2, name: 'Lulu Hypermarket Deira City Centre', location: 'Dubai' },
  { id: 3, name: 'Lulu Hypermarket Karama', location: 'Dubai' },
  { id: 4, name: 'Lulu Hypermarket Mushrif Mall', location: 'Abu Dhabi' },
  { id: 5, name: 'Lulu Hypermarket Al Wahda', location: 'Abu Dhabi' },
  { id: 6, name: 'Lulu Hypermarket Khalidiyah', location: 'Abu Dhabi' },
  { id: 7, name: 'Lulu Hypermarket Sharjah City Centre', location: 'Sharjah' },
  { id: 8, name: 'Lulu Hypermarket Al Nahda', location: 'Sharjah' },
  { id: 9, name: 'Lulu Hypermarket Ajman', location: 'Ajman' },
  { id: 10, name: 'Lulu Hypermarket Ras Al Khaimah', location: 'Ras Al Khaimah' },
];

const ROLES = [
  { value: 'sales_executive', label: 'Sales Executive' },
  { value: 'senior_sales', label: 'Senior Sales' },
  { value: 'team_lead', label: 'Team Lead' },
  { value: 'assistant_manager', label: 'Assistant Manager' },
  { value: 'store_manager', label: 'Store Manager' },
  { value: 'regional_manager', label: 'Regional Manager' },
  { value: 'cashier', label: 'Cashier' },
  { value: 'inventory_clerk', label: 'Inventory Clerk' },
  { value: 'customer_service', label: 'Customer Service' },
];

const DEPARTMENTS = [
  { value: 'sales', label: 'Sales' },
  { value: 'management', label: 'Management' },
  { value: 'inventory', label: 'Inventory' },
  { value: 'customer_service', label: 'Customer Service' },
  { value: 'finance', label: 'Finance' },
  { value: 'hr', label: 'Human Resources' },
  { value: 'it', label: 'IT' },
  { value: 'logistics', label: 'Logistics' },
  { value: 'marketing', label: 'Marketing' },
];

const NATIONALITIES = [
  'UAE', 'India', 'Pakistan', 'Philippines', 'Bangladesh',
  'Egypt', 'Sri Lanka', 'Nepal', 'Jordan', 'Lebanon', 'Other'
];

export default function NewEmployeeModal({ isOpen, onClose, onSuccess }: NewEmployeeModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [step, setStep] = useState(1);

  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    date_of_birth: '',
    gender: '',
    nationality: '',
    role: 'sales_executive',
    department: 'sales',
    designation: '',
    store_id: '',
    date_of_joining: new Date().toISOString().split('T')[0],
  });

  if (!isOpen) return null;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    setError(null);
  };

  const validateStep = (currentStep: number): boolean => {
    setError(null);

    if (currentStep === 1) {
      if (!formData.first_name.trim()) { setError('First name is required'); return false; }
      if (!formData.last_name.trim()) { setError('Last name is required'); return false; }
      if (!formData.email.trim()) { setError('Email is required'); return false; }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) { setError('Invalid email format'); return false; }
    }

    if (currentStep === 2) {
      if (!formData.role) { setError('Role is required'); return false; }
      if (!formData.department) { setError('Department is required'); return false; }
      if (!formData.store_id) { setError('Please select a store'); return false; }
      if (!formData.date_of_joining) { setError('Date of joining is required'); return false; }
    }

    return true;
  };

  const handleNext = () => {
    if (validateStep(step)) {
      setStep(2);
    }
  };

  const handleBack = () => {
    setStep(1);
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateStep(2)) return;

    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const payload: Record<string, unknown> = {
        first_name: formData.first_name.trim(),
        last_name: formData.last_name.trim(),
        email: formData.email.trim().toLowerCase(),
        role: formData.role,
        department: formData.department,
        store_id: parseInt(formData.store_id),
        date_of_joining: formData.date_of_joining,
      };

      if (formData.phone.trim()) payload.phone = formData.phone.trim();
      if (formData.designation.trim()) payload.designation = formData.designation.trim();
      if (formData.date_of_birth) payload.date_of_birth = formData.date_of_birth;
      if (formData.gender) payload.gender = formData.gender;
      if (formData.nationality) payload.nationality = formData.nationality;

      const res = await fetch(`${API_URL}/api/employees/employees`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const result = await res.json();
        setSuccess(`Employee ${result.employee?.employee_code || ''} created successfully!`);
        setTimeout(() => {
          onSuccess();
          onClose();
          // Reset form
          setFormData({
            first_name: '', last_name: '', email: '', phone: '',
            date_of_birth: '', gender: '', nationality: '',
            role: 'sales_executive', department: 'sales', designation: '',
            store_id: '', date_of_joining: new Date().toISOString().split('T')[0],
          });
          setStep(1);
          setSuccess(null);
        }, 1500);
      } else {
        const errData = await res.json();
        setError(errData.detail || 'Failed to create employee');
      }
    } catch (err) {
      setError('Network error. Please check your connection and try again.');
    } finally {
      setLoading(false);
    }
  };

  const selectedStore = STORES.find(s => s.id === parseInt(formData.store_id));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-800 rounded-2xl w-full max-w-xl shadow-2xl m-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-blue-600 to-indigo-600 rounded-t-2xl">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-white/20 rounded-xl flex items-center justify-center">
              <User className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Add New Employee</h2>
              <p className="text-blue-100 text-xs">Step {step} of 2 — {step === 1 ? 'Personal Info' : 'Employment Details'}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-lg transition-colors">
            <X className="w-5 h-5 text-white" />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-1 bg-gray-200 dark:bg-gray-700">
          <div className={`h-full bg-blue-500 transition-all duration-300 ${step === 1 ? 'w-1/2' : 'w-full'}`} />
        </div>

        {/* Success message */}
        {success && (
          <div className="mx-6 mt-4 p-3 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400 flex-shrink-0" />
            <span className="text-green-700 dark:text-green-300 text-sm">{success}</span>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="mx-6 mt-4 p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0" />
            <span className="text-red-700 dark:text-red-300 text-sm">{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Step 1: Personal Information */}
          {step === 1 && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    First Name <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <User className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                    <input
                      type="text" name="first_name" value={formData.first_name}
                      onChange={handleChange} placeholder="John"
                      className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Last Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text" name="last_name" value={formData.last_name}
                    onChange={handleChange} placeholder="Doe"
                    className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Email <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                  <input
                    type="email" name="email" value={formData.email}
                    onChange={handleChange} placeholder="john.doe@lulu.ae"
                    className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Phone
                </label>
                <div className="relative">
                  <Phone className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                  <input
                    type="tel" name="phone" value={formData.phone}
                    onChange={handleChange} placeholder="+971 50 123 4567"
                    className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Date of Birth
                  </label>
                  <div className="relative">
                    <Calendar className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                    <input
                      type="date" name="date_of_birth" value={formData.date_of_birth}
                      onChange={handleChange}
                      className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Gender
                  </label>
                  <select
                    name="gender" value={formData.gender} onChange={handleChange}
                    className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  >
                    <option value="">Select...</option>
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Non-binary">Non-binary</option>
                    <option value="Prefer not to say">Prefer not to say</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Nationality
                </label>
                <div className="relative">
                  <Globe className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                  <select
                    name="nationality" value={formData.nationality} onChange={handleChange}
                    className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  >
                    <option value="">Select nationality...</option>
                    {NATIONALITIES.map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
              </div>
            </>
          )}

          {/* Step 2: Employment Details */}
          {step === 2 && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Role <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <Briefcase className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                    <select
                      name="role" value={formData.role} onChange={handleChange}
                      className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                    >
                      {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Department <span className="text-red-500">*</span>
                  </label>
                  <select
                    name="department" value={formData.department} onChange={handleChange}
                    className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  >
                    {DEPARTMENTS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Designation / Job Title
                </label>
                <input
                  type="text" name="designation" value={formData.designation}
                  onChange={handleChange} placeholder="e.g. Senior Sales Associate"
                  className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Assigned Store <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Building className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                  <select
                    name="store_id" value={formData.store_id} onChange={handleChange}
                    className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  >
                    <option value="">Select a store...</option>
                    {STORES.map(s => (
                      <option key={s.id} value={s.id}>{s.name} ({s.location})</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Date of Joining <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <Calendar className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
                  <input
                    type="date" name="date_of_joining" value={formData.date_of_joining}
                    onChange={handleChange}
                    className="w-full pl-10 pr-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                  />
                </div>
              </div>

              {/* Preview Card */}
              <div className="mt-2 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl">
                <h4 className="text-sm font-semibold text-blue-800 dark:text-blue-300 mb-2">Preview</h4>
                <div className="grid grid-cols-2 gap-2 text-xs text-blue-700 dark:text-blue-400">
                  <div><span className="font-medium">Name:</span> {formData.first_name} {formData.last_name}</div>
                  <div><span className="font-medium">Email:</span> {formData.email}</div>
                  <div><span className="font-medium">Role:</span> {ROLES.find(r => r.value === formData.role)?.label}</div>
                  <div><span className="font-medium">Dept:</span> {DEPARTMENTS.find(d => d.value === formData.department)?.label}</div>
                  <div><span className="font-medium">Store:</span> {selectedStore?.name || 'Not selected'}</div>
                  <div><span className="font-medium">Joining:</span> {formData.date_of_joining}</div>
                </div>
              </div>
            </>
          )}

          {/* Buttons */}
          <div className="flex justify-between pt-2">
            {step === 1 ? (
              <>
                <button
                  type="button" onClick={onClose}
                  className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors text-sm"
                >
                  Cancel
                </button>
                <button
                  type="button" onClick={handleNext}
                  className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
                >
                  Next →
                </button>
              </>
            ) : (
              <>
                <button
                  type="button" onClick={handleBack}
                  className="px-4 py-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors text-sm"
                >
                  ← Back
                </button>
                <button
                  type="submit" disabled={loading || !!success}
                  className="flex items-center gap-2 px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
                >
                  {loading ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Creating...</>
                  ) : success ? (
                    <><CheckCircle className="w-4 h-4" /> Created!</>
                  ) : (
                    'Create Employee'
                  )}
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
