'use client';

import { useState, FormEvent } from 'react';
import { Modal, Input, Select, Button } from '@/components/ui';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/contexts/AuthContext';

interface NewUserModalProps {
  open: boolean;
  onClose: () => void;
  /** Called after a successful create so the parent can refresh the list. */
  onCreated: () => void;
}

const ROLES = [
  { value: 'analyst', label: 'Analyst' },
  { value: 'store_manager', label: 'Store Manager' },
  { value: 'regional_manager', label: 'Regional Manager' },
  { value: 'super_admin', label: 'Super Admin' },
];

const EMPTY = { first_name: '', last_name: '', email: '', password: '', role: 'analyst' };

export function NewUserModal({ open, onClose, onCreated }: NewUserModalProps) {
  const { authFetch } = useAuth();
  const toast = useToast();
  const [form, setForm] = useState({ ...EMPTY });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof typeof EMPTY, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!form.first_name.trim() || !form.last_name.trim() || !form.email.trim()) {
      setError('First name, last name and email are required.');
      return;
    }
    if (form.password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await authFetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || body.message || `Request failed (${res.status})`);
      }
      toast.show(`${form.email} can now sign in.`, { variant: 'success', title: 'User created' });
      setForm({ ...EMPTY });
      onCreated();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to create user.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Add new user" size="md">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Input label="First name" value={form.first_name} onChange={(e) => set('first_name', e.target.value)} autoFocus />
          <Input label="Last name" value={form.last_name} onChange={(e) => set('last_name', e.target.value)} />
        </div>
        <Input label="Email" type="email" value={form.email} onChange={(e) => set('email', e.target.value)} placeholder="name@company.com" />
        <Input
          label="Temporary password"
          type="password"
          value={form.password}
          onChange={(e) => set('password', e.target.value)}
          placeholder="At least 8 characters"
        />
        <Select label="Role" value={form.role} onChange={(e) => set('role', e.target.value)}>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </Select>
        {error && <p className="text-sm text-coral-600">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={submitting}>Create user</Button>
        </div>
      </form>
    </Modal>
  );
}
