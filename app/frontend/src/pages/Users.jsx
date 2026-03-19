/** @fileoverview User management — "Who's uploading?" modal + user CRUD. */
import { signal } from "@preact/signals";
import { useEffect } from "preact/hooks";
import { ShModal } from "superhot-ui/preact";
import { ShDataTable } from "superhot-ui/preact";
import { fmtDateTime } from "../lib/format.js";

/** Reactive state */
const userList = signal([]);
const loading = signal(true);
const showNewInput = signal(false);
const newName = signal("");
const creating = signal(false);
const deleteTarget = signal(null);
const deleting = signal(false);
const errorMsg = signal("");

/** Fetch all users from API. */
function fetchUsers() {
  return fetch("/api/users")
    .then((resp) => resp.json())
    .then((data) => {
      userList.value = data;
      loading.value = false;
    })
    .catch((err) => {
      console.warn("Users: fetch failed", err);
      loading.value = false;
    });
}

/** Create a new user via API. */
function createUser() {
  const name = newName.value.trim();
  if (!name) return;

  creating.value = true;
  errorMsg.value = "";

  fetch("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
    body: JSON.stringify({ name }),
  })
    .then((resp) => {
      if (resp.status === 409) {
        errorMsg.value = "NAME EXISTS";
        return null;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return resp.json();
    })
    .then((data) => {
      if (data) {
        newName.value = "";
        showNewInput.value = false;
        fetchUsers();
      }
    })
    .catch((err) => {
      console.warn("Users: create failed", err);
      errorMsg.value = "CREATE FAILED";
    })
    .finally(() => {
      creating.value = false;
    });
}

/** Delete a user via API. */
function confirmDelete() {
  const target = deleteTarget.value;
  if (!target || deleting.value) return;

  deleting.value = true;

  fetch(`/api/users/${target.id}`, {
    method: "DELETE",
    headers: { "X-Requested-With": "XMLHttpRequest" },
  })
    .then((resp) => {
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      fetchUsers();
    })
    .catch((err) => {
      console.warn("Users: delete failed", err);
    })
    .finally(() => {
      deleting.value = false;
      deleteTarget.value = null;
    });
}

/**
 * Users — user management page.
 * Lists all users with upload counts, allows create and delete.
 */
export function Users() {
  useEffect(() => {
    fetchUsers();
  }, []);

  if (loading.value) {
    return (
      <div class="sh-frame" style="padding: 24px; text-align: center;">
        <div class="sh-ansi-dim">STANDBY</div>
      </div>
    );
  }

  const columns = [
    { key: "name", label: "USER", sortable: true },
    { key: "upload_count", label: "UPLOADS", sortable: true },
    { key: "last_upload_fmt", label: "LAST UPLOAD", sortable: true },
    { key: "actions", label: "" },
  ];

  const rows = userList.value.map((user) => ({
    ...user,
    last_upload_fmt: fmtDateTime(user.last_upload_at),
    actions: user.name === "default" ? "" : (
      <button
        class="sh-btn sh-btn-sm"
        data-sh-status="critical"
        onClick={(evt) => {
          evt.stopPropagation();
          deleteTarget.value = user;
        }}
        style="font-size: 0.7rem; padding: 2px 6px;"
      >
        DELETE
      </button>
    ),
  }));

  const target = deleteTarget.value;
  const isDeleting = deleting.value;

  return (
    <div class="sh-animate-page-enter fc-page">
      {/* User table */}
      {rows.length > 0 ? (
        <ShDataTable
          label="USERS"
          columns={columns}
          rows={rows}
          searchable={false}
        />
      ) : (
        <div class="sh-frame" data-label="USERS">
          <div style="padding: 24px; text-align: center;">
            <div class="sh-ansi-dim">NO DATA</div>
          </div>
        </div>
      )}

      {/* Create user */}
      <div class="sh-frame" data-label="NEW USER">
        <div style="padding: 12px;">
          {showNewInput.value ? (
            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
              <input
                class="sh-input"
                type="text"
                placeholder="NAME"
                value={newName.value}
                onInput={(evt) => { newName.value = evt.target.value; }}
                onKeyDown={(evt) => { if (evt.key === "Enter") createUser(); }}
                style="flex: 1; min-width: 120px;"
                autofocus
              />
              <button
                class="sh-btn"
                onClick={createUser}
                disabled={creating.value || !newName.value.trim()}
              >
                {creating.value ? "STANDBY" : "CREATE"}
              </button>
              <button
                class="sh-btn"
                onClick={() => {
                  showNewInput.value = false;
                  newName.value = "";
                  errorMsg.value = "";
                }}
              >
                CANCEL
              </button>
              {errorMsg.value && (
                <span class="sh-status-badge" data-sh-status="critical" style="font-size: 0.75rem;">
                  {errorMsg.value}
                </span>
              )}
            </div>
          ) : (
            <button
              class="sh-btn"
              onClick={() => { showNewInput.value = true; }}
            >
              + NEW USER
            </button>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      <ShModal
        open={!!target}
        title="CONFIRM: DELETE USER"
        body={target ? `Remove "${target.name}"? Photos will be reassigned to DEFAULT.` : ""}
        confirmLabel={isDeleting ? "DELETING..." : "DELETE"}
        cancelLabel="CANCEL"
        onConfirm={confirmDelete}
        onCancel={() => { deleteTarget.value = null; }}
      />
    </div>
  );
}


// --- "Who's uploading?" modal for Upload page integration ---

/** Current user signal — read from cookie or null. */
export const currentUser = signal(_readUserCookie());

/** Whether the user selection modal is open. */
export const showUserModal = signal(false);

/** Read the framecast_user cookie. */
function _readUserCookie() {
  const match = document.cookie.match(/(?:^|;\s*)framecast_user=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/** Set the framecast_user cookie (30 days). */
function _setUserCookie(name) {
  const expires = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toUTCString();
  document.cookie = `framecast_user=${encodeURIComponent(name)};path=/;expires=${expires};SameSite=Strict`;
  currentUser.value = name;
}

/**
 * Check if user identification is needed before upload.
 * Returns true if the modal was shown (caller should wait).
 */
export function ensureUserIdentified() {
  if (currentUser.value) return false;
  showUserModal.value = true;
  return true;
}

/**
 * UserSelectModal — "WHO IS UPLOADING?" overlay.
 * Shows user list + new user input. Sets cookie on selection.
 *
 * @param {object} props
 * @param {Function} [props.onSelected] — called with username after selection
 */
export function UserSelectModal({ onSelected }) {
  const users = signal([]);
  const newInput = signal("");
  const isCreating = signal(false);

  useEffect(() => {
    if (showUserModal.value) {
      fetch("/api/users")
        .then((resp) => resp.json())
        .then((data) => { users.value = data; })
        .catch((err) => console.warn("UserSelectModal: fetch failed", err));
    }
  }, [showUserModal.value]);

  function selectUser(name) {
    _setUserCookie(name);
    showUserModal.value = false;
    onSelected?.(name);
  }

  function createAndSelect() {
    const name = newInput.value.trim();
    if (!name) return;
    isCreating.value = true;

    fetch("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ name }),
    })
      .then((resp) => {
        if (!resp.ok && resp.status !== 409) throw new Error(`HTTP ${resp.status}`);
        // Even on 409 (already exists), select the user
        selectUser(name);
      })
      .catch((err) => {
        console.warn("UserSelectModal: create failed", err);
        // Fall back to just setting cookie with entered name
        selectUser(name);
      })
      .finally(() => {
        isCreating.value = false;
        newInput.value = "";
      });
  }

  if (!showUserModal.value) return null;

  return (
    <div class="sh-modal-overlay" style="z-index: 1000;">
      <div class="sh-modal" role="dialog" aria-modal="true" aria-label="User selection">
        <div class="sh-modal-title">WHO IS UPLOADING?</div>
        <div class="sh-modal-body" style="max-height: 300px; overflow-y: auto;">
          {users.value.length === 0 ? (
            <div class="sh-ansi-dim" style="padding: 8px 0;">STANDBY</div>
          ) : (
            <div style="display: grid; gap: 6px;">
              {users.value.map((user) => (
                <button
                  key={user.id}
                  class="sh-btn"
                  style="text-align: left; width: 100%;"
                  onClick={() => selectUser(user.name)}
                >
                  {user.name.toUpperCase()}
                  {user.upload_count > 0 && (
                    <span class="sh-ansi-dim" style="margin-left: 8px; font-size: 0.75rem;">
                      ({user.upload_count})
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}

          {/* New user input */}
          <div style="margin-top: 12px; border-top: 1px solid var(--border-primary, #333); padding-top: 12px;">
            <div class="sh-label" style="margin-bottom: 6px;">NEW USER</div>
            <div style="display: flex; gap: 8px;">
              <input
                class="sh-input"
                type="text"
                placeholder="NAME"
                value={newInput.value}
                onInput={(evt) => { newInput.value = evt.target.value; }}
                onKeyDown={(evt) => { if (evt.key === "Enter") createAndSelect(); }}
                style="flex: 1;"
              />
              <button
                class="sh-btn"
                onClick={createAndSelect}
                disabled={isCreating.value || !newInput.value.trim()}
              >
                {isCreating.value ? "STANDBY" : "GO"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
