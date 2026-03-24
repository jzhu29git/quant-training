import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import {
  getExplorerCatalog,
  getExplorerQuery,
  type ExplorerDataset,
  type ExplorerFilter
} from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatBytes, formatDateTime, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";

export const dynamic = "force-dynamic";

type SearchValue = string | string[] | undefined;

function firstValue(value: SearchValue) {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function allValues(value: SearchValue) {
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function buildFilterSlots(params: Record<string, SearchValue>) {
  const filters: ExplorerFilter[] = [];
  for (let index = 1; index <= 3; index += 1) {
    const column = String(firstValue(params[`f${index}_column`]) ?? "").trim();
    const operator = String(firstValue(params[`f${index}_operator`]) ?? "").trim();
    const value = String(firstValue(params[`f${index}_value`]) ?? "").trim();
    const valueTo = String(firstValue(params[`f${index}_value_to`]) ?? "").trim();
    if (!column || !operator) {
      continue;
    }
    filters.push({
      column,
      operator,
      value: value || undefined,
      value_to: valueTo || undefined
    });
  }
  return filters;
}

function pageHref({
  dataset,
  search,
  page,
  pageSize,
  sortBy,
  sortDir,
  columns,
  filters,
  exportFormat
}: {
  dataset: string;
  search: string;
  page: number;
  pageSize: number;
  sortBy: string;
  sortDir: string;
  columns: string[];
  filters: ExplorerFilter[];
  exportFormat?: string;
}) {
  const query = new URLSearchParams();
  query.set("dataset", dataset);
  if (search.trim()) {
    query.set("search", search.trim());
  }
  query.set("page", String(page));
  query.set("page_size", String(pageSize));
  query.set("sort_by", sortBy);
  query.set("sort_dir", sortDir);
  for (const column of columns) {
    query.append("columns", column);
  }
  filters.forEach((filter, index) => {
    query.set(`f${index + 1}_column`, filter.column);
    query.set(`f${index + 1}_operator`, filter.operator);
    if (filter.value) {
      query.set(`f${index + 1}_value`, filter.value);
    }
    if (filter.value_to) {
      query.set(`f${index + 1}_value_to`, filter.value_to);
    }
  });
  if (exportFormat) {
    query.set("export_format", exportFormat);
    return `/data/export?${query.toString()}`;
  }
  return `/data?${query.toString()}`;
}

function queryHint(dataset: ExplorerDataset, isZh: boolean) {
  return isZh
    ? `${dataset.description} 檔案更新於 ${formatDateTime(dataset.updated_at, "zh-Hant")}`
    : `${dataset.description} Updated ${formatDateTime(dataset.updated_at, "en")}`;
}

export default async function DataPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, SearchValue>>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const isZh = user.locale === "zh-Hant";
  const params = (await searchParams) ?? {};
  const catalog = await getExplorerCatalog();
  const availableDatasets = catalog.datasets.filter((dataset) => dataset.column_count > 0);
  const fallbackDataset = availableDatasets[0] ?? catalog.datasets[0];
  const datasetKey = String(firstValue(params.dataset) ?? fallbackDataset?.key ?? "training_features");
  const dataset = catalog.datasets.find((item) => item.key === datasetKey) ?? fallbackDataset;

  if (!dataset) {
    return (
      <Shell
        title={isZh ? "Data Explorer" : "Data Explorer"}
        subtitle={isZh ? "目前沒有可查詢的 parquet dataset。" : "No parquet datasets are available for exploration yet."}
        locale={user.locale}
        username={user.username}
        role={user.role}
      >
        <Panel title={isZh ? "沒有資料" : "No Data"}>
          <p className="empty-state">{copy.common.noRows}</p>
        </Panel>
      </Shell>
    );
  }

  const search = String(firstValue(params.search) ?? "").trim();
  const page = Math.max(Number.parseInt(String(firstValue(params.page) ?? "1"), 10) || 1, 1);
  const pageSize = Math.min(Math.max(Number.parseInt(String(firstValue(params.page_size) ?? "50"), 10) || 50, 1), 200);
  const sortBy = String(firstValue(params.sort_by) ?? dataset.default_columns[0] ?? dataset.columns[0]?.name ?? "date");
  const sortDir = String(firstValue(params.sort_dir) ?? "desc");
  const selectedColumns = allValues(params.columns).filter((value) => dataset.columns.some((column) => column.name === value));
  const filters = buildFilterSlots(params);

  const result = await getExplorerQuery({
    dataset: dataset.key,
    search,
    filters,
    columns: selectedColumns,
    sort_by: sortBy,
    sort_dir: sortDir,
    page,
    page_size: pageSize
  });

  const paginationBase = {
    dataset: dataset.key,
    search,
    pageSize: result.page_size,
    sortBy: result.sort_by,
    sortDir: result.sort_dir,
    columns: result.selected_columns,
    filters
  };

  return (
    <Shell
      title={isZh ? "Data Explorer" : "Data Explorer"}
      subtitle={
        isZh
          ? "直接查 Step 2 到 Step 5 的全量 parquet 表。這裡支援 dataset 切換、搜尋、欄位篩選、排序、分頁與匯出。"
          : "Explore the full step 2 to step 5 parquet datasets with search, filters, sorting, paging, and export from one place."
      }
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <section className="metrics-grid">
        <MetricCard label={isZh ? "目前 Dataset" : "Current Dataset"} value={dataset.label} hint={dataset.key} />
        <MetricCard label={isZh ? "總筆數" : "Total Rows"} value={formatNumber(result.total_rows, user.locale)} hint={isZh ? "落地 parquet 總列數" : "Rows in saved parquet"} />
        <MetricCard label={isZh ? "查詢結果" : "Filtered Rows"} value={formatNumber(result.filtered_rows, user.locale)} hint={isZh ? "符合目前查詢條件" : "Rows matching current query"} />
        <MetricCard label={isZh ? "欄位數" : "Columns"} value={formatNumber(dataset.column_count, user.locale)} hint={formatBytes(dataset.size_bytes, user.locale)} />
        <MetricCard label={isZh ? "頁面" : "Page"} value={`${result.page}/${result.total_pages}`} hint={`${formatNumber(result.page_size, user.locale)} ${isZh ? "列 / 頁" : "rows / page"}`} />
        <MetricCard label={isZh ? "檔案更新" : "Updated"} value={formatDateTime(dataset.updated_at, user.locale)} hint={dataset.path} />
      </section>

      <section className="explorer-layout">
        <Panel title={isZh ? "Datasets" : "Datasets"}>
          <div className="dataset-catalog">
            {catalog.datasets.map((item) => (
              <a
                key={item.key}
                href={`/data?dataset=${item.key}`}
                className={`dataset-card ${item.key === dataset.key ? "dataset-card-active" : ""}`}
              >
                <strong>{item.label}</strong>
                <span>{formatNumber(item.row_count, user.locale)} {isZh ? "筆" : "rows"}</span>
                <span>{formatNumber(item.column_count, user.locale)} {isZh ? "欄" : "cols"}</span>
                <span>{formatDateTime(item.updated_at, user.locale)}</span>
              </a>
            ))}
          </div>
        </Panel>

        <div className="explorer-main">
          <Panel
            title={isZh ? "Query Builder" : "Query Builder"}
            aside={<span className="pill">{queryHint(dataset, isZh)}</span>}
          >
            <form method="get" action="/data" className="explorer-form">
              <input type="hidden" name="dataset" value={dataset.key} />
              <div className="explorer-form-grid">
                <label className="field-block">
                  <span>{isZh ? "搜尋" : "Search"}</span>
                  <input type="text" name="search" defaultValue={search} placeholder={isZh ? "code / name / industry" : "code / name / industry"} />
                </label>
                <label className="field-block">
                  <span>{isZh ? "排序欄位" : "Sort By"}</span>
                  <select name="sort_by" defaultValue={result.sort_by}>
                    {dataset.columns.map((column) => (
                      <option key={column.name} value={column.name}>
                        {column.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-block">
                  <span>{isZh ? "排序方向" : "Sort Direction"}</span>
                  <select name="sort_dir" defaultValue={result.sort_dir}>
                    <option value="desc">{isZh ? "遞減" : "Descending"}</option>
                    <option value="asc">{isZh ? "遞增" : "Ascending"}</option>
                  </select>
                </label>
                <label className="field-block">
                  <span>{isZh ? "每頁筆數" : "Rows Per Page"}</span>
                  <select name="page_size" defaultValue={String(result.page_size)}>
                    {[25, 50, 100, 200].map((size) => (
                      <option key={size} value={size}>
                        {size}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="filter-builder">
                {[1, 2, 3].map((index) => {
                  const current = filters[index - 1];
                  return (
                    <div key={index} className="filter-row">
                      <select name={`f${index}_column`} defaultValue={current?.column ?? ""}>
                        <option value="">{isZh ? `Filter ${index} 欄位` : `Filter ${index} Column`}</option>
                        {dataset.columns.map((column) => (
                          <option key={column.name} value={column.name}>
                            {column.name}
                          </option>
                        ))}
                      </select>
                      <select name={`f${index}_operator`} defaultValue={current?.operator ?? ""}>
                        <option value="">{isZh ? "條件" : "Operator"}</option>
                        <option value="eq">=</option>
                        <option value="neq">!=</option>
                        <option value="gt">&gt;</option>
                        <option value="gte">&gt;=</option>
                        <option value="lt">&lt;</option>
                        <option value="lte">&lt;=</option>
                        <option value="between">{isZh ? "區間" : "Between"}</option>
                        <option value="contains">{isZh ? "包含" : "Contains"}</option>
                        <option value="starts_with">{isZh ? "前綴" : "Starts With"}</option>
                        <option value="ends_with">{isZh ? "後綴" : "Ends With"}</option>
                        <option value="is_null">{isZh ? "為空" : "Is Null"}</option>
                        <option value="not_null">{isZh ? "非空" : "Not Null"}</option>
                      </select>
                      <input type="text" name={`f${index}_value`} defaultValue={current?.value ?? ""} placeholder={isZh ? "值" : "Value"} />
                      <input type="text" name={`f${index}_value_to`} defaultValue={current?.value_to ?? ""} placeholder={isZh ? "第二值 / 區間上限" : "Second Value / Upper Bound"} />
                    </div>
                  );
                })}
              </div>

              <div className="column-picker">
                {dataset.columns.map((column) => {
                  const checked = result.selected_columns.includes(column.name);
                  return (
                    <label key={column.name} className="checkbox-chip">
                      <input type="checkbox" name="columns" value={column.name} defaultChecked={checked} />
                      <span>{column.name}</span>
                      <small>{column.type}</small>
                    </label>
                  );
                })}
              </div>

              <div className="action-row">
                <button className="auth-submit action-button" type="submit">
                  {isZh ? "套用查詢" : "Apply Query"}
                </button>
                <a href={`/data?dataset=${dataset.key}`} className="action-button secondary-button">
                  {isZh ? "重設" : "Reset"}
                </a>
                <a href={pageHref({ ...paginationBase, page: 1, exportFormat: "csv" })} className="action-button secondary-button">
                  {isZh ? "匯出 CSV" : "Export CSV"}
                </a>
                <a href={pageHref({ ...paginationBase, page: 1, exportFormat: "parquet" })} className="action-button secondary-button">
                  {isZh ? "匯出 Parquet" : "Export Parquet"}
                </a>
              </div>

              <p className="panel-copy">
                {isZh
                  ? `匯出上限為 ${formatNumber(result.max_export_rows, user.locale)} 筆。若要匯出更多，先縮小條件。`
                  : `Exports are capped at ${formatNumber(result.max_export_rows, user.locale)} rows. Narrow the query first if you need more.`}
              </p>
            </form>
          </Panel>

          <Panel
            title={isZh ? "Result Table" : "Result Table"}
            aside={<span className="pill">{formatNumber(result.filtered_rows, user.locale)} {isZh ? "筆" : "rows"}</span>}
          >
            <div className="status-meta">
              <span>{isZh ? "搜尋" : "Search"}: {result.search || "—"}</span>
              <span>{isZh ? "排序" : "Sort"}: {result.sort_by} / {result.sort_dir}</span>
              <span>{isZh ? "欄位" : "Columns"}: {result.selected_columns.join(", ") || "—"}</span>
            </div>
            <DataTable
              rows={result.rows}
              columns={result.selected_columns.map((column) => ({ key: column, label: column }))}
              emptyLabel={copy.common.noRows}
              locale={user.locale}
            />
            <div className="pagination-row">
              <a
                href={pageHref({ ...paginationBase, page: Math.max(1, result.page - 1) })}
                className={`action-button secondary-button ${result.page <= 1 ? "button-disabled" : ""}`}
                aria-disabled={result.page <= 1}
              >
                {isZh ? "上一頁" : "Previous"}
              </a>
              <span className="pill">
                {isZh ? "第" : "Page"} {result.page} / {result.total_pages}
              </span>
              <a
                href={pageHref({ ...paginationBase, page: Math.min(result.total_pages, result.page + 1) })}
                className={`action-button secondary-button ${result.page >= result.total_pages ? "button-disabled" : ""}`}
                aria-disabled={result.page >= result.total_pages}
              >
                {isZh ? "下一頁" : "Next"}
              </a>
            </div>
          </Panel>
        </div>
      </section>
    </Shell>
  );
}
