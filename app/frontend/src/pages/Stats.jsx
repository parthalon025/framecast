/** @fileoverview Stats dashboard — aggregated content and display statistics. */
import { signal } from "@preact/signals";
import { useEffect } from "preact/hooks";
import { useState } from "preact/hooks";
import { ShStatsGrid } from "superhot-ui/preact";
import { ShStatCard } from "superhot-ui/preact";
import { ShDataTable } from "superhot-ui/preact";
import { ShFrozen } from "superhot-ui/preact";
import { ShCollapsible, ShSkeleton } from "superhot-ui/preact";
import { fmtDateTime } from "../lib/format.js";
import { fetchWithTimeout } from "../lib/fetch.js";

/** Storage breakdown bar chart. */
function StorageBreakdown({ breakdown }) {
  if (!breakdown) return null;
  const items = [
    { label: "PHOTOS", value: breakdown.photos, human: breakdown.photos_human, color: "var(--sh-phosphor)" },
    { label: "THUMBNAILS", value: breakdown.thumbnails, human: breakdown.thumbnails_human, color: "var(--text-muted, #666)" },
    { label: "DATABASE", value: breakdown.database, human: breakdown.database_human, color: "var(--status-warning, #f59e0b)" },
  ];
  const total = items.reduce((sum, item) => sum + item.value, 0) || 1;

  return (
    <div class="fc-storage-breakdown">
      {items.map((item) => (
        <div key={item.label} class="fc-storage-row">
          <span class="sh-label" style="min-width: 90px;">{item.label}</span>
          <div class="fc-storage-bar-bg">
            <div
              class="fc-storage-bar-fill"
              style={{ width: `${(item.value / total) * 100}%`, background: item.color }}
            />
          </div>
          <span class="sh-value" style="min-width: 60px; text-align: right;">{item.human}</span>
        </div>
      ))}
    </div>
  );
}

/** Reactive state */
const stats = signal(null);
const loading = signal(true);
const error = signal(null);
const lastUpdated = signal(null);

/** Fetch stats from API. */
function fetchStats() {
  loading.value = true;
  error.value = null;
  return fetchWithTimeout("/api/stats")
    .then((resp) => {
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return resp.json();
    })
    .then((data) => {
      stats.value = data;
      lastUpdated.value = Date.now();
      loading.value = false;
    })
    .catch((err) => {
      console.warn("Stats: fetch failed", err);
      error.value = "FETCH FAILED";
      loading.value = false;
    });
}

/**
 * ActivityLog — recent uploads fetched from /api/photos.
 */
function ActivityLog() {
  const [activity, setActivity] = useState(null);

  useEffect(() => {
    fetch("/api/photos")
      .then((resp) => resp.json())
      .then((photos) => setActivity(photos.slice(0, 10)))
      .catch(() => setActivity([]));
  }, []);

  if (!activity) return <ShSkeleton rows={3} height="2em" />;
  if (activity.length === 0) return <span class="sh-label">NO UPLOADS</span>;

  return (
    <div class="fc-activity-list">
      {activity.map((photo) => (
        <div key={photo.id} class="fc-activity-row">
          <span class="sh-ansi-dim" style="font-size: 0.75rem;">
            {photo.uploaded_at ? photo.uploaded_at.replace("T", " ").slice(0, 16) : "UNKNOWN"}
          </span>
          <span class="sh-value" style="flex: 1; overflow: hidden; text-overflow: ellipsis;">
            {photo.name || photo.filename}
          </span>
          <span class="sh-ansi-dim" style="font-size: 0.75rem;">
            {photo.uploaded_by || "default"}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Stats — dashboard page with ShStatsGrid, ShStatCard, and ShDataTable.
 */
export function Stats() {
  useEffect(() => {
    fetchStats();
  }, []);

  if (loading.value) {
    return (
      <div class="sh-frame" style="padding: 24px; text-align: center;">
        <div class="sh-ansi-dim">STANDBY</div>
      </div>
    );
  }

  if (error.value) {
    return (
      <div class="sh-frame" style="padding: 24px; text-align: center;">
        <div class="sh-status-badge" data-sh-status="critical">{error.value}</div>
        <button
          class="sh-btn"
          style="margin-top: 12px;"
          onClick={fetchStats}
        >
          RETRY
        </button>
      </div>
    );
  }

  const data = stats.value;
  if (!data) {
    return (
      <div class="sh-frame" style="padding: 24px; text-align: center;">
        <div class="sh-ansi-dim">NO DATA</div>
      </div>
    );
  }

  // Summary stat cards
  const summaryStats = [
    { label: "PHOTOS", value: data.total_photos ?? 0 },
    { label: "VIDEOS", value: data.total_videos ?? 0 },
    { label: "STORAGE", value: data.storage_used ?? "0 B" },
    { label: "VIEWS", value: data.total_views ?? 0 },
  ];

  // Uploads by user table
  const userColumns = [
    { key: "uploaded_by", label: "USER", sortable: true },
    { key: "count", label: "COUNT", sortable: true },
    { key: "last_upload_fmt", label: "LAST UPLOAD", sortable: true },
  ];
  const userRows = (data.by_user || []).map((row) => ({
    ...row,
    last_upload_fmt: fmtDateTime(row.last_upload),
  }));

  // Most shown table
  const mostShownColumns = [
    { key: "filename", label: "FILE", sortable: true },
    { key: "view_count", label: "VIEWS", sortable: true },
    { key: "last_shown_fmt", label: "LAST SHOWN", sortable: true },
  ];
  const mostShownRows = (data.most_shown || []).map((row) => ({
    ...row,
    last_shown_fmt: fmtDateTime(row.last_shown_at),
  }));

  // Least shown table (NEGLECTED)
  const leastShownColumns = [
    { key: "filename", label: "FILE", sortable: true },
    { key: "view_count", label: "VIEWS", sortable: true },
    { key: "uploaded_at_fmt", label: "UPLOADED", sortable: true },
  ];
  const leastShownRows = (data.least_shown || []).map((row) => ({
    ...row,
    uploaded_at_fmt: fmtDateTime(row.uploaded_at),
  }));

  return (
    <ShFrozen timestamp={lastUpdated} class="sh-animate-page-enter fc-page">
      {/* Summary cards */}
      <div class="sh-frame" data-label="OVERVIEW">
        <div style="padding: 12px;">
          <ShStatsGrid stats={summaryStats} cols={2} />
          {data.avg_duration != null && (
            <div class="sh-ansi-dim" style="margin-top: 12px; font-size: 0.8rem;">
              AVG DISPLAY: {data.avg_duration}s
              {data.never_shown_count > 0 && (
                <span> | NEVER SHOWN: {data.never_shown_count}</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Storage breakdown */}
      {data.storage_breakdown && (
        <div class="sh-frame" data-label="STORAGE BREAKDOWN">
          <div style="padding: 12px;">
            <StorageBreakdown breakdown={data.storage_breakdown} />
          </div>
        </div>
      )}

      {/* Recent activity */}
      <ShCollapsible title="RECENT ACTIVITY" defaultOpen={true}>
        <ActivityLog />
      </ShCollapsible>

      {/* Uploads by user */}
      {userRows.length > 0 ? (
        <ShDataTable
          label="UPLOADS BY USER"
          columns={userColumns}
          rows={userRows}
          searchable={false}
        />
      ) : (
        <div class="sh-frame" data-label="UPLOADS BY USER">
          <div style="padding: 24px; text-align: center;">
            <div class="sh-ansi-dim">NO DATA</div>
          </div>
        </div>
      )}

      {/* Most shown */}
      {mostShownRows.length > 0 ? (
        <ShDataTable
          label="MOST SHOWN"
          columns={mostShownColumns}
          rows={mostShownRows}
          searchable={false}
        />
      ) : (
        <div class="sh-frame" data-label="MOST SHOWN">
          <div style="padding: 24px; text-align: center;">
            <div class="sh-ansi-dim">NO DATA</div>
          </div>
        </div>
      )}

      {/* Least shown (NEGLECTED) */}
      {leastShownRows.length > 0 ? (
        <ShDataTable
          label="NEGLECTED"
          columns={leastShownColumns}
          rows={leastShownRows}
          searchable={false}
        />
      ) : (
        <div class="sh-frame" data-label="NEGLECTED">
          <div style="padding: 24px; text-align: center;">
            <div class="sh-ansi-dim">NO DATA</div>
          </div>
        </div>
      )}

      {/* Upload timeline (ASCII bar chart) */}
      {data.timeline && data.timeline.length > 0 && (
        <div class="sh-frame" data-label="UPLOAD TIMELINE (30 DAYS)">
          <div style="padding: 12px; font-family: var(--font-mono, monospace); font-size: 0.75rem;">
            {data.timeline.map((day) => {
              const maxCount = Math.max(...data.timeline.map((d) => d.count));
              const barLen = maxCount > 0 ? Math.max(1, Math.round((day.count / maxCount) * 20)) : 0;
              return (
                <div key={day.date} style="display: flex; gap: 8px; line-height: 1.6;">
                  <span class="sh-ansi-dim" style="min-width: 80px;">{day.date}</span>
                  <span style="color: var(--sh-phosphor, #0f0);">{"\u2593".repeat(barLen)}</span>
                  <span class="sh-ansi-dim">{day.count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </ShFrozen>
  );
}
