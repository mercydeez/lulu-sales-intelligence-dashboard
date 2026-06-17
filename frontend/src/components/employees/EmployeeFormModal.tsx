'use client';

import { useEffect, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { Modal, Input, Select, Button } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { fetchStores } from '@/lib/api';
import { Store } from '@/types';

interface EmployeeFormModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const ROLES = [
  ['sales_executive', 'Sales Executive'], ['senior_sales', 'Senior Sales'], ['team_lead', 'Team Lead'],
  ['assistant_manager', 'Assistant Manager'], ['store_manager', 'Store Manager'], ['regional_manager', 'Regional Manager'],
  ['cashier', 'Cashier'], ['inventory_clerk', 'Inventory Clerk'], ['customer_service', 'Customer Service'],
];
const DEPARTMENTS = [
  ['sales', 'Sales'], ['management', 'Management'], ['inventory', 'Inventory'], ['customer_service', 'Customer Service'],
  ['finance', 'Finance'], ['hr', 'Human Resources'], ['it', 'IT'], ['logistics', 'Logistics'], ['marketing', 'Marketing'],
];
const NATIONALITIES = ['UAE', 'India', 'Pakistan', 'Philippines', 'Bangladesh', 'Egypt', 'Sri Lanka', 'Nepal', 'Jordan', 'Lebanon', 'Other'];

const blank = {
  first_name: '', last_name: '', email: '', phone: '', designation: '',
  role: 'sales_executive', department: 'sales', store_id: '',
  date_of_joining: new Date().toISOString().split('T')[0],
  date_of_birth: '', gender: '', nationality: '',
};

export function EmployeeFormModal({ open, onClose, onSuccess }: EmployeeFormModalProps) {
  const { authFetch } = useAuth();
  const [stores, setStores] = useState<Store[]>([]);
  const [form, setForm] = useState({ ...blank });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm({ ...blank });
    setError(null);
    fetchStores().then(setStores).catch(() => setStores([]));
  }, [open]);

  const set = (key: keyof typeof blank, value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  const validate = (): string | null => {
    if (!form.first_name.trim()) return 'First name is required';
    if (!form.last_name.trim()) return 'Last name is required';
    if (!form.email.trim()) return 'Email is required';
    if (!form.store_id) return 'Please select a store';
    if (!form.date_of_joining) return 'Date of joining is required';
    return null;
  };

  const handleSubmit = async () => {
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        email: form.email.trim().toLowerCase(),
        role: form.role,
        department: form.department,
        store_id: parseInt(form.store_id, 10),
        date_of_joining: form.date_of_joining,
      };
      if (form.phone.trim()) payload.phone = form.phone.trim();
      if (form.designation.trim()) payload.designation = form.designation.trim();
      if (form.date_of_birth) payload.date_of_birth = form.date_of_birth;
      if (form.gender) payload.gender = form.gender;
      if (form.nationality) payload.nationality = form.nationality;

      const res = await authFetch('/api/employees/employees', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        onSuccess();
        onClose();
      } else {
        const body = await res.json().catch(() => ({}));
        setError(body.detail || 'Failed to create employee');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Add New Employee" size="lg">
      <div className="space-y-4 max-h-[65vh] overflow-y-auto pr-1">
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Input label="First Name" value={form.first_name} onChange={(e) => set('first_name', e.target.value)} />
          <Input label="Last Name" value={form.last_name} onChange={(e) => set('last_name', e.target.value)} />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Input label="Email" type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
          <Input label="Phone" value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="+971..." />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Select label="Role" value={form.role} onChange={(e) => set('role', e.target.value)}>
            {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          <Select label="Department" value={form.department} onChange={(e) => set('department', e.target.value)}>
            {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Input label="Designation (optional)" value={form.designation} onChange={(e) => set('designation', e.target.value)} />
          <Select label="Store" value={form.store_id} onChange={(e) => set('store_id', e.target.value)}>
            <option value="">Select a store…</option>
            {stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Input label="Date of Joining" type="date" value={form.date_of_joining} onChange={(e) => set('date_of_joining', e.target.value)} />
          <Input label="Date of Birth (optional)" type="date" value={form.date_of_birth} onChange={(e) => set('date_of_birth', e.target.value)} />
          <Select label="Gender (optional)" value={form.gender} onChange={(e) => set('gender', e.target.value)}>
            <option value="">—</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
          </Select>
        </div>

        <Select label="Nationality (optional)" value={form.nationality} onChange={(e) => set('nationality', e.target.value)}>
          <option value="">—</option>
          {NATIONALITIES.map((n) => <option key={n} value={n}>{n}</option>)}
        </Select>
      </div>

      <div className="flex gap-3 pt-5">
        <Button variant="secondary" className="flex-1" onClick={onClose}>Cancel</Button>
        <Button variant="primary" className="flex-1" onClick={handleSubmit} loading={submitting}>Add Employee</Button>
      </div>
    </Modal>
  );
}
