'use client';

import { useMemo } from 'react';
import { Search, Users, UserPlus } from 'lucide-react';
import { Card, Input, Button, Table, TableHead, TableBody, TableRow, Th, Td, Badge, SkeletonText, EmptyState } from '@/components/ui';
import { AdminUser } from './types';
import { roleLabel, roleVariant, formatDate, formatRelative } from './format';

interface UsersTableProps {
  users: AdminUser[];
  loading: boolean;
  search: string;
  onSearchChange: (v: string) => void;
  onAddUser?: () => void;
}

export function UsersTable({ users, loading, search, onSearchChange, onAddUser }: UsersTableProps) {
  const filtered = useMemo(
    () =>
      users.filter(
        (u) =>
          `${u.first_name} ${u.last_name}`.toLowerCase().includes(search.toLowerCase()) ||
          u.email.toLowerCase().includes(search.toLowerCase()) ||
          roleLabel(u.role).toLowerCase().includes(search.toLowerCase())
      ),
    [users, search]
  );

  return (
    <Card variant="glass" padding="none">
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-b border-coral-100">
        <div>
          <h3 className="text-lg font-semibold text-ink">Users &amp; Access</h3>
          <p className="text-sm text-ink-muted mt-0.5">Platform accounts and their roles</p>
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="w-full sm:w-64">
            <Input
              icon={<Search className="w-4 h-4" />}
              placeholder="Search users..."
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              className="!py-2.5"
            />
          </div>
          {onAddUser && (
            <Button variant="primary" size="md" onClick={onAddUser} className="shrink-0 whitespace-nowrap">
              <UserPlus className="w-4 h-4" />
              Add user
            </Button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="p-5"><SkeletonText lines={6} /></div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={<Users className="w-6 h-6" />} title="No users found" description={search ? 'Try a different search.' : 'No accounts to show.'} />
      ) : (
        <Table>
          <TableHead>
            <TableRow>
              <Th>User</Th>
              <Th>Role</Th>
              <Th className="text-center">Status</Th>
              <Th>Joined</Th>
              <Th>Last login</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((u) => (
              <TableRow key={u.id}>
                <Td>
                  <div className="min-w-0">
                    <p className="font-medium text-ink truncate">{u.first_name} {u.last_name}</p>
                    <p className="text-xs text-ink-muted truncate">{u.email}</p>
                  </div>
                </Td>
                <Td><Badge variant={roleVariant(u.role)} size="sm">{roleLabel(u.role)}</Badge></Td>
                <Td className="text-center">
                  <Badge 