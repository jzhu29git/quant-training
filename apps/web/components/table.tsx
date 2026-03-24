import type { PanelLocale } from "@/lib/i18n";
import { formatDisplayValue } from "@/lib/format";

type TableRow = Record<string, unknown>;

export function DataTable({
  rows,
  columns,
  emptyLabel,
  locale = "en"
}: {
  rows: TableRow[];
  columns?: Array<string | { key: string; label: string }>;
  emptyLabel?: string;
  locale?: PanelLocale;
}) {
  if (!rows.length) {
    return <p className="empty-state">{emptyLabel ?? "No rows to display."}</p>;
  }

  const headers = columns ?? Object.keys(rows[0]);
  const normalizedHeaders = headers.map((header) =>
    typeof header === "string" ? { key: header, label: header } : header
  );

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {normalizedHeaders.map((header) => (
              <th key={header.key}>{header.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${index}-${normalizedHeaders[0]?.key ?? "row"}`}>
              {normalizedHeaders.map((header) => (
                <td key={header.key}>{formatDisplayValue(row[header.key], { locale, key: header.key })}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
