'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Badge, Button, Select, EmptyState, useToast,
  NoPermissionState,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';
import { apiGet, apiPost, ApiError } from '@/lib/apiClient';
import { UploadCloud, FileSpreadsheet, CheckCircle2, AlertTriangle } from 'lucide-react';

interface Field { key: string; required: boolean; kind: string; hint: string; }
interface SchemaT { import_type: string; target: string; fields: Field[]; }
interface ValidationSummary { total: number; valid: number; errors: number; error_fields?: number; }
interface RowError { row: number; field: string; message: string; }
interface Job { id: number; import_type: string; status: string; total_rows: number;
  imported_rows: number; skipped_rows: number; error_rows: number; created_at: string | null; }

const TYPE_LABEL: Record<string, string> = {
  stores: 'Stores', items: 'Products / SKUs', sales: 'Sales history',
  inventory: 'Inventory levels', suppliers: 'Suppliers',
};
const JOB_TONE: Record<string, BadgeVariant> = { completed: 'success', partial: 'amber', failed: 'danger' };

// Guess a source column for a canonical field by fuzzy name match.
function guessColumn(field: Field, headers: string[]): string {
  const want = [field.key, ...field.hint.toLowerCase().split(/[^a-z]+/)].filter(Boolean);
  const lower = headers.map((h) => h.toLowerCase());
  for (let i = 0; i < headers.length; i++) {
    if (want.some((w) => w.length > 2 && lower[i].includes(w))) return headers[i];
  }
  if (lower.includes(field.key)) return headers[lower.indexOf(field.key)];
  return '';
}

export default function ImportsPage() {
  const { user } = useAuth();
  const { show } = useToast();
  const isOperator = ['super_admin', 'admin', 'regional_manager', 'store_manager'].includes(user?.role ?? '')
    || !!user?.permissions?.can_manage_inventory;

  const [schemas, setSchemas] = useState<SchemaT[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [step, setStep] = useState<'upload' | 'map' | 'done'>('upload');
  const [importType, setImportType] = useState('items');
  const [filename, setFilename] = useState('');
  const [csvText, setCsvText] = useState('');
  // Excel workbooks travel base64 (E1-3); exactly one of csvText / fileB64 is set.
  const [fileB64, setFileB64] = useState('');
  const [headers, setHeaders] = useState<string[]>([]);
  const [sample, setSample] = useState<Record<string, string>[]>([]);
  const [rowCount, setRowCount] = useState(0);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [validation, setValidation] = useState<{ summary: ValidationSummary; errors: RowError[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const schema = schemas.find((s) => s.import_type === importType);

  const loadMeta = useCallback(async () => {
    try {
      const [t, j] = await Promise.all([
        apiGet<{ types: SchemaT[] }>('/api/imports/types'),
        apiGet<{ jobs: Job[] }>('/api/imports'),
      ]);
      setSchemas(t.types ?? []);
      setJobs(j.jobs ?? []);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { if (isOperator) loadMeta(); }, [isOperator, loadMeta]);

  // A CSV is sent as text; an Excel workbook is sent base64 (E1-3). The backend
  // sniffs the real format from the file's magic bytes and parses both into the
  // same rows, so the map/validate/commit path is literally identical.
  const isExcelName = (n: string) => /\.(xlsx|xls)$/i.test(n);

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFilename(file.name);
    if (isExcelName(file.name)) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let bin = '';
      // Chunked: String.fromCharCode(...bigArray) blows the argument limit.
      for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      }
      setFileB64(btoa(bin));
      setCsvText('');
    } else {
      setCsvText(await file.text());
      setFileB64('');
    }
  };

  /** Whichever source the user picked — exactly one is ever set. */
  const sourceBody = () => (fileB64 ? { file_b64: fileB64 } : { csv_text: csvText });
  const hasSource = Boolean(csvText || fileB64);

  const analyze = async () => {
    if (!hasSource) { show('Choose a CSV or Excel file first', { variant: 'error' }); return; }
    setBusy(true);
    try {
      const res = await apiPost<{ headers: string[]; sample: Record<string, string>[]; row_count: number }>(
        '/api/imports/analyze', sourceBody());
      setHeaders(res.headers);
      setSample(res.sample);
      setRowCount(res.row_count);
      const sch = schemas.find((s) => s.import_type === importType);
      const auto: Record<string, string> = {};
      sch?.fields.forEach((f) => { auto[f.key] = guessColumn(f, res.headers); });
      setMapping(auto);
      setValidation(null);
      setStep('map');
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Could not read the CSV', { variant: 'error' });
    } finally { setBusy(false); }
  };

  const validate = async () => {
    setBusy(true);
    try {
      setValidation(await apiPost('/api/imports/validate', { import_type: importType, mapping, ...sourceBody() }));
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Validation failed', { variant: 'error' });
    } finally { setBusy(false); }
  };

  const commit = async () => {
    setBusy(true);
    try {
      const res = await apiPost<{ imported: number; skipped: number }>(
        '/api/imports/commit', { import_type: importType, mapping, ...sourceBody(), filename });
      show(`Imported ${res.imported} row(s)${res.skipped ? `, skipped ${res.skipped}` : ''}`, { variant: 'success' });
      setStep('done');
      await loadMeta();
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Import failed', { variant: 'error' });
    } finally { setBusy(false); }
  };

  const reset = () => { setStep('upload'); setCsvText(''); setFileB64(''); setFilename(''); setHeaders([]); setSample([]); setValidation(null); };

  const downloadSample = async (format: 'csv' | 'xlsx' = 'csv') => {
    try {
      const { authFetch } = (await import('@/lib/apiClient'));
      const res = await authFetch(`/api/imports/sample/${importType}?format=${format}`);
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `sample-${importType}.${format}`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  };

  if (!isOperator) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="none">
          <NoPermissionState
            title="Operator access required"
            description="Data imports are limited to operator roles. Ask a workspace admin if you need access."
          />
        </Card>
      </div></main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader
          title="Import data"
          description="Upload your sales, inventory, products or stores as CSV or Excel. Map your columns, we validate every row, then it's live."
          icon={<UploadCloud className="w-5 h-5" />}
        />

        {step === 'upload' && (
          <Card padding="lg">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <Select label="What are you importing?" value={importType} onChange={(e) => setImportType(e.target.value)}>
                {schemas.map((s) => <option key={s.import_type} value={s.import_type}>{TYPE_LABEL[s.import_type] ?? s.import_type}</option>)}
              </Select>
              <div>
                <label className="block text-sm font-medium text-ink-soft mb-2">CSV or Excel file</label>
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                  onChange={onFile}
                  className="block w-full text-sm text-ink-soft file:me-3 file:py-2 file:px-3 file:rounded-lg file:border file:border-line file:bg-surface-2 file:text-ink hover:file:bg-surface-3" />
              </div>
            </div>
            {schema && (
              <div className="rounded-xl bg-surface-2/60 p-3 mb-4 text-xs text-ink-soft">
                <span className="font-medium">Expected columns: </span>
                {schema.fields.map((f) => (
                  <span key={f.key} className="me-2">
                    {f.key}{f.required ? '*' : ''} <span className="text-ink-muted">({f.hint})</span>
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-center gap-2 flex-wrap">
              <Button onClick={analyze} disabled={busy || !hasSource}>
                <FileSpreadsheet className="w-4 h-4 me-1.5" /> {busy ? 'Reading…' : 'Continue'}
              </Button>
              <Button variant="secondary" onClick={() => downloadSample('csv')}>
                <FileSpreadsheet className="w-4 h-4 me-1.5" /> Download sample CSV
              </Button>
              <Button variant="secondary" onClick={() => downloadSample('xlsx')}>
                <FileSpreadsheet className="w-4 h-4 me-1.5" /> Download sample Excel
              </Button>
            </div>
            <p className="text-xs text-ink-muted mt-3">
              No data handy? Download a sample, then upload it back to try the full flow.
            </p>
          </Card>
        )}

        {step === 'map' && schema && (
          <div className="space-y-6">
            <Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-1">Map your columns</h3>
              <p className="text-xs text-ink-muted mb-4">{filename} · {rowCount.toLocaleString()} rows detected</p>
              <div className="space-y-3">
                {schema.fields.map((f) => (
                  <div key={f.key} className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center">
                    <div className="text-sm">
                      <span className="text-ink font-medium">{f.key}</span>{f.required && <span className="text-rose-500"> *</span>}
                      <span className="block text-xs text-ink-muted">{f.hint}</span>
                    </div>
                    <Select value={mapping[f.key] ?? ''} onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value }))}>
                      <option value="">— not mapped —</option>
                      {headers.map((h) => <option key={h} value={h}>{h}</option>)}
                    </Select>
                  </div>
                ))}
              </div>
            </Card>

            {sample.length > 0 && (
              <Card padding="lg">
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-3">Preview</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="text-ink-muted"><tr>{headers.map((h) => <th key={h} className="text-start p-1.5">{h}</th>)}</tr></thead>
                    <tbody>{sample.map((r, i) => (
                      <tr key={i} className="border-t border-line/60">{headers.map((h) => <td key={h} className="p-1.5 text-ink-soft">{r[h]}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
              </Card>
            )}

            {validation && (
              <Card padding="lg">
                <div className="flex items-center gap-3 mb-3">
                  <Badge variant={validation.summary.valid > 0 ? 'success' : 'danger'}>{validation.summary.valid} valid</Badge>
                  {validation.summary.errors > 0 && <Badge variant="amber">{validation.summary.errors} rows with errors</Badge>}
                </div>
                {validation.errors.length > 0 && (
                  <ul className="text-xs text-ink-soft space-y-1 max-h-48 overflow-y-auto">
                    {validation.errors.slice(0, 30).map((e, i) => (
                      <li key={i}><span className="text-rose-500">Row {e.row}</span> · {e.field}: {e.message}</li>
                    ))}
                  </ul>
                )}
              </Card>
            )}

            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={reset}>Back</Button>
              <Button variant="secondary" onClick={validate} disabled={busy}><AlertTriangle className="w-4 h-4 me-1.5" /> Validate</Button>
              <Button onClick={commit} disabled={busy || !validation || validation.summary.valid === 0}>
                <CheckCircle2 className="w-4 h-4 me-1.5" /> Import {validation ? `${validation.summary.valid} rows` : ''}
              </Button>
            </div>
          </div>
        )}

        {step === 'done' && (
          <Card padding="lg" className="text-center">
            <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-ink">Import complete</h3>
            <p className="text-sm text-ink-muted mt-1 mb-4">Your data is live. See the Value screen for the impact in AED.</p>
            <Button onClick={reset}>Import another file</Button>
          </Card>
        )}

        {/* History */}
        <div className="mt-8">
          <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-3">Recent imports</h3>
          {jobs.length === 0 ? <EmptyState title="No imports yet" description="Your import history will appear here." />
          : (
            <div className="space-y-2">
              {jobs.map((j) => (
                <div key={j.id} className="flex items-center justify-between gap-3 rounded-xl border border-line p-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink">{TYPE_LABEL[j.import_type] ?? j.import_type}</p>
                    <p className="text-xs text-ink-muted">
                      {j.imported_rows} imported{j.skipped_rows ? ` · ${j.skipped_rows} skipped` : ''}{j.error_rows ? ` · ${j.error_rows} errors` : ''}
                      {j.created_at ? ` · ${new Date(j.created_at).toLocaleString()}` : ''}
                    </p>
                  </div>
                  <Badge variant={JOB_TONE[j.status] ?? 'neutral'}>{j.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
