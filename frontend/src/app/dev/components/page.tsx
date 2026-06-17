'use client';

import { useState } from 'react';
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip } from 'recharts';
import {
  Layers,
  ShoppingBag,
  TrendingUp,
  Package,
  Search,
  Mail,
  Inbox,
} from 'lucide-react';
import {
  Button,
  Card,
  CardHeader,
  CardTitle,
  Badge,
  BadgeVariant,
  Input,
  Select,
  Table,
  TableHead,
  TableBody,
  TableRow,
  Th,
  Td,
  Modal,
  Skeleton,
  SkeletonCard,
  SkeletonText,
  StatCard,
  ToastProvider,
  useToast,
  EmptyState,
  ChartFrame,
  LiveIndicator,
  PageHeader,
  Tabs,
} from '@/components/ui';

const badgeVariants: BadgeVariant[] = ['coral', 'teal', 'violet', 'amber', 'neutral', 'success', 'warning', 'danger'];

const sampleChartData = [
  { day: 'Mon', units: 320 },
  { day: 'Tue', units: 410 },
  { day: 'Wed', units: 380 },
  { day: 'Thu', units: 460 },
  { day: 'Fri', units: 520 },
  { day: 'Sat', units: 610 },
  { day: 'Sun', units: 540 },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card variant="glass" padding="lg" className="space-y-4">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      {children}
    </Card>
  );
}

function ToastDemo() {
  const { show } = useToast();
  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="secondary" onClick={() => show('Inventory synced successfully.', { title: 'Success', variant: 'success' })}>
        Success
      </Button>
      <Button variant="secondary" onClick={() => show('Could not reach the server.', { title: 'Error', variant: 'error' })}>
        Error
      </Button>
      <Button variant="secondary" onClick={() => show('3 items are expiring this week.', { title: 'Warning', variant: 'warning' })}>
        Warning
      </Button>
      <Button variant="secondary" onClick={() => show('A new forecast run is available.', { title: 'Info', variant: 'info' })}>
        Info
      </Button>
    </div>
  );
}

function ComponentGallery() {
  const [modalOpen, setModalOpen] = useState(false);
  const [tab, setTab] = useState('overview');

  return (
    <div className="max-w-6xl mx-auto px-6 py-10 space-y-8">
      <PageHeader
        title="Component Gallery"
        description="Dev-only showcase of every ui/ primitive — Phase 3.2"
        icon={<Layers className="w-5 h-5" />}
        actions={<Badge variant="violet">dev only</Badge>}
      />

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="primary" loading>Loading</Button>
          <Button variant="primary" disabled>Disabled</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm">Small</Button>
          <Button size="md">Medium</Button>
          <Button size="lg">Large</Button>
        </div>
      </Section>

      <Section title="Badges">
        <div className="flex flex-wrap gap-2">
          {badgeVariants.map((v) => (
            <Badge key={v} variant={v}>{v}</Badge>
          ))}
        </div>
      </Section>

      <Section title="Cards">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card variant="glass" hover="lift">Glass + lift hover</Card>
          <Card variant="solid" hover="pop">Solid + pop hover</Card>
          <Card variant="glass" padding="sm">Compact padding</Card>
        </div>
      </Section>

      <Section title="Stat cards">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatCard label="Total Stores" value="10" icon={<ShoppingBag className="w-5 h-5" />} tone="coral" trend="up" trendLabel="+2 this month" />
          <StatCard label="Low Stock Items" value="45" icon={<Package className="w-5 h-5" />} tone="amber" trend="down" trendLabel="-5 vs last week" />
          <StatCard label="Today's Revenue" value="AED 48.2K" icon={<TrendingUp className="w-5 h-5" />} tone="violet" variant="gradient" footnote="Volume: 1,204 units" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatCard label="Loading example" value="" loading />
        </div>
      </Section>

      <Section title="Live indicator">
        <div className="flex flex-wrap items-center gap-6">
          <LiveIndicator tone="teal" />
          <LiveIndicator tone="coral" label="STREAMING" />
          <LiveIndicator tone="rose" label="ALERT" size="sm" />
          <LiveIndicator tone="violet" label="SYNCING" />
        </div>
      </Section>

      <Section title="Inputs &amp; select">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input label="Email" type="email" placeholder="you@lulu.ae" icon={<Mail className="w-4 h-4" />} />
          <Input label="Search" placeholder="Search items..." icon={<Search className="w-4 h-4" />} />
          <Input label="With error" defaultValue="bad value" error="This field is required" />
          <Select label="Region">
            <option>Dubai</option>
            <option>Abu Dhabi</option>
            <option>Sharjah</option>
          </Select>
        </div>
      </Section>

      <Section title="Tabs">
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            { id: 'overview', label: 'Overview' },
            { id: 'inventory', label: 'Inventory' },
            { id: 'alerts', label: 'Alerts' },
          ]}
        />
        <p className="text-sm text-ink-muted">Active tab: <span className="font-medium text-ink">{tab}</span></p>
      </Section>

      <Section title="Table">
        <Table>
          <TableHead>
            <TableRow>
              <Th>Item</Th>
              <Th>Store</Th>
              <Th>Status</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <Td>Basmati Rice 5kg</Td>
              <Td>Al Barsha</Td>
              <Td><Badge variant="success" size="sm">In stock</Badge></Td>
            </TableRow>
            <TableRow>
              <Td>Fresh Milk 1L</Td>
              <Td>Deira</Td>
              <Td><Badge variant="warning" size="sm">Low stock</Badge></Td>
            </TableRow>
          </TableBody>
        </Table>
      </Section>

      <Section title="Modal">
        <Button onClick={() => setModalOpen(true)}>Open modal</Button>
        <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Example modal">
          <p className="text-sm text-ink-soft">This is modal content. Press Escape or click outside to close.</p>
        </Modal>
      </Section>

      <Section title="Toast">
        <ToastDemo />
      </Section>

      <Section title="Skeleton">
        <div className="space-y-4">
          <SkeletonCard className="max-w-xs" />
          <SkeletonText lines={3} className="max-w-md" />
        </div>
      </Section>

      <Section title="Empty state">
        <EmptyState
          icon={<Inbox className="w-7 h-7" />}
          title="No alerts right now"
          description="New alerts will show up here as soon as they're triggered."
          action={<Button size="sm">Refresh</Button>}
        />
      </Section>

      <Section title="Chart frame">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ChartFrame title="Units sold" subtitle="Last 7 days" live height={220}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sampleChartData}>
                <XAxis dataKey="day" stroke="var(--chart-text)" fontSize={12} />
                <YAxis stroke="var(--chart-text)" fontSize={12} />
                <Tooltip />
                <Line type="monotone" dataKey="units" stroke="#ff6b5c" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
          <ChartFrame title="Loading example" height={220} loading />
          <ChartFrame title="Empty example" height={220} empty />
        </div>
      </Section>
    </div>
  );
}

export default function ComponentGalleryPage() {
  return (
    <ToastProvider>
      <ComponentGallery />
    </ToastProvider>
  );
}
