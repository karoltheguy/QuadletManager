# Plan: Address Missing Features in QuadletManager

**TL;DR:** Wire up existing syntax validation, seed missing templates, then add admin UI for server/key management with a new RBAC admin role. Support both paste and file upload for SSH keys.

---

## Phase 1: Quick Wins (1-2 hours)

*These can be done in parallel*

1. **Wire up syntax validation on save**
   - Modify `api/routes.py` → `save_file()` function
   - Call `validate_quadlet_syntax()` before writing content
   - Return validation errors as JSON response
   - Add error toast/alert in frontend `static/main.js`

2. **Seed all default templates**
   - Modify `core/database.py` → template seeding logic
   - Add templates for: Volume, Network, Pod types
   - Use boilerplate from Podman Quadlet documentation

---

## Phase 2: Admin Role & API (3-4 hours)

3. **Add admin role to RBAC**
   - Modify `core/database.py` → add `is_admin` boolean column to users table
   - Modify `api/routes.py` → add `require_admin` decorator
   - Update existing permission checks

4. **Server Management API**
   - Add to `api/routes.py`:
     - `GET /api/servers` - list all servers
     - `POST /api/servers` - add new server
     - `PUT /api/servers/<id>` - edit server
     - `DELETE /api/servers/<id>` - delete server

5. **SSH Key Management API**
   - Add to `api/routes.py`:
     - `GET /api/keys` - list user's keys
     - `POST /api/keys` - upload key (paste or file)
     - `DELETE /api/keys/<id>` - delete key
   - Handle encryption using existing `crypto.py`

---

## Phase 3: Admin UI (2-3 hours)

*depends on Phase 2*

6. **Admin panel template**
   - Create `static/templates/admin.html` partial or add section to dashboard
   - Forms for:
     - Add/Edit server (host, port, username, scope)
     - Upload SSH key (textarea + file input)
     - List existing servers/keys with delete buttons

7. **Wire admin UI to API**
   - Modify `static/main.js`
   - Add admin section rendering
   - Handle form submissions
   - Refresh navigator after server changes

---

## Phase 4: Polish & Tests (2-3 hours)

*depends on Phases 1-3*

8. **File deletion**
   - Add `DELETE /api/files` endpoint
   - Add delete button to tree view context menu
   - Add confirmation modal

9. **E2E tests for documented scenarios**
   - Polling alert test (touch remote file → verify banner within 10s)
   - Template injection test (New from Template → verify editor content)

---

## Relevant Files

| File | What to modify |
|------|----------------|
| `api/routes.py` | Add validation call, server/key CRUD endpoints, admin decorator |
| `services/quadlet_parser.py` | Contains `validate_quadlet_syntax()` to reuse |
| `core/database.py` | Add `is_admin` column, seed all template types |
| `static/main.js` | Handle validation errors, admin UI, file deletion |
| `static/templates/dashboard.html` | Add admin panel section |
| `tests/test_e2e.py` | Add polling alert and template tests |

---

## Verification

1. **Syntax validation**: Create invalid quadlet → save → see error message, file not saved
2. **Templates**: Click "New from Template" → see all 4 types in dropdown
3. **Server management**: Login as admin → add server → appears in navigator
4. **SSH key upload**: Paste key OR upload .pem file → encrypted in DB → connection works
5. **File deletion**: Right-click file in tree → delete → confirm → removed from tree and filesystem
6. **E2E tests**: `pytest tests/` passes all tests including new scenarios

---

## Decisions

- Admin access via new `is_admin` role in RBAC system
- SSH key upload supports BOTH paste (textarea) and file upload
- Default templates will be system-wide (not per-user)

---

## Further Considerations

1. **Should the admin panel be a separate page or integrated into the existing dashboard?**
   - Recommendation: Add as a collapsible side panel or tab in the existing dashboard to keep the UI unified.

2. **Should non-admin users see the admin section grayed out, or completely hidden?**
   - Recommendation: Completely hidden - cleaner UX, users don't see what they can't access.
