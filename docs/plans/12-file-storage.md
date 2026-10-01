# 12. File storage: image galleries and documents on S3-compatible storage

> **Status: planned, not started.** Sequenced after `docs/plans/10-profile-editing.md`, `docs/plans/11-search.md` and the Row-Level Security rollout (see `docs/plans/0-production-readiness-roadmap.md`), because organization documents are a new organization-owned table. Private API only.

## Goal

A production-ready file-storage slice that many applications need:

1. **Image galleries:** users and organizations each hold an **array of images** (a gallery), not a single avatar or logo.
2. **Documents:** users and organizations can upload files such as PDFs and images, kept private.
3. **Storage:** files are stored through one port, on the local disk by default, or on any S3-compatible service (AWS S3, Cloudflare R2, MinIO) selected by configuration.

## User stories

| Story | As a | I want | So that | Acceptance criteria |
|---|---|---|---|---|
| 1. Profile image | user | to upload an image to my gallery | people see my picture | JPEG, PNG or WebP, up to 5MB, checked by content, not extension<br>At most 1 image; a second upload is 409 until I delete the first<br>The response gives a public URL that opens in a browser |
| 2. Organization gallery | organization OWNER or ADMIN | to upload, delete and reorder my organization's images | its gallery shows what I choose, first image as the logo | At most `STORAGE_ORGANIZATION_IMAGES_MAX` images (default 10)<br>The first image in gallery order is the primary one<br>A MEMBER gets 403; an outsider gets 404 |
| 3. Private documents | user | to upload PDFs and images only I can see | I can keep my files with my account | PDF, JPEG, PNG or WebP by content; up to 10 files of 10MB each<br>Each listed document has a `url`, filename, file type, size, uploader and upload time<br>No other user can list or download them |
| 4. Organization documents | organization OWNER or ADMIN | to upload and delete documents for my organization | every member can get at the files they need | Upload by OWNER or ADMIN is 201; by a MEMBER is 403<br>Any member can list and download them |
| 5. Tenant privacy | organization OWNER | outsiders to be unable to change my organization's gallery or reach its documents | our files stay inside the organization | An outsider gets 404 for the organization's gallery changes and documents<br>Downloads go through an authorized route or a short-lived signed URL |
| 6. Storage choice | platform admin | to switch storage between local disk and S3-compatible services by configuration | the app runs cheaply by default and scales when needed | `STORAGE_BACKEND=local` by default; `s3` for AWS S3, Cloudflare R2 or MinIO<br>Nothing about the API changes when the backend changes |

## Reference implementation

apptension/saas-boilerplate (https://github.com/apptension/saas-boilerplate), `packages/backend/`:
- **Storage:** `common/storages.py` selects the backend via `STORAGE_BACKEND` (`s3`, `r2`, `b2`, `minio` or `local`), using django-storages' `S3Boto3Storage`.
  - Cloudflare R2 needs `signature_version="s3v4"` and `default_acl=None`.
  - Public and private files share one bucket, split by key prefix: `public/` files are served unsigned, and everything else needs a signed URL.
  - Local development uses LocalStack.
- **Keys:** `UniqueFilePathGenerator` builds keys as `prefix/<random hex>/<filename>`, so two uploads never collide.
- **Avatars:** `apps/users/models.py` has `UserAvatar`, a single image per user with a 128x128 Pillow thumbnail (`common/models.py`, `ImageWithThumbnailMixin`). The size limit is 1MB, but type is checked **by file extension only**.
- **Uploads:** uploads go directly through the backend (multipart); apptension has no presigned upload URLs.
- **Documents:** `apps/demo/models.py` has `DocumentDemoItem`. It belongs to one user, uses private storage, and has limits of 10 files and 10MB each, but **no file-type check at all**. Only the owner can list or delete their documents, and deleting the row also deletes the stored file.
- **What apptension doesn't have:** a tenant logo, or image arrays of any kind.

Where this plan departs from apptension, and why:
- **An image array** instead of one avatar, as the human maintainer asked.
- **Content-based type checks:** validation reads the file's actual contents (Pillow must be able to open an image; a PDF must start with `%PDF-`), not just its name, because an extension check is trivially bypassed.
- **Local disk as the default backend**, per `agents.md` 4.1 (smallest viable infrastructure). S3-compatible storage is a configuration switch, not a requirement.

## Design

### The port: storage-agnostic

`core/common/ports/file_storage.py`, a `FileStorage` Protocol:
- `save(key, content, content_type)`
- `delete(key)`
- `open(key)`, used to stream a private file through the app
- `url(key, *, private)`: a URL a client can use to fetch the file

The entities (image, document) and the port know nothing about S3, disks or buckets. They deal only in a storage key, a content type and a size. Only the adapters care about a specific implementation. For example, `S3CompatibleFileStorage.url(private=True)` returns a presigned S3 URL, while `LocalDiskFileStorage.url(private=True)` returns the app's own authorized download route. Swapping storage never touches the domain or the use cases.

**The port must not assume S3.** A future deployment may use Google Firebase Storage (built on Google Cloud Storage), which has no S3 API at all. So the port's vocabulary is deliberately generic:
- a key, bytes, a content type, and a URL
- no buckets, ACLs, regions, endpoints or "presigned" concepts; those are adapter configuration

Firebase then becomes one more sibling adapter, `FirebaseFileStorage`, with no change to the port, entities or use cases:
- `url(private=True)` becomes a signed Cloud Storage URL.
- `url(private=False)` becomes a public download URL.
- It adds one more `STORAGE_BACKEND` value.

It isn't built in this plan. The `S3CompatibleFileStorage` and `LocalDiskFileStorage` adapter tests are written against the port's contract, so a Firebase adapter can reuse the same contract tests.

### Adapters (named after their mechanism, per `agents.md` 4.3)

- **`LocalDiskFileStorage` (the default):** writes under a configurable directory, a Docker volume in Compose. Public images are served by a small read-only route. It is correct for a single-server deployment, and needs no new infrastructure.
- **`S3CompatibleFileStorage`:** one adapter for AWS S3, Cloudflare R2 and MinIO, differing only in configuration:
  - `STORAGE_S3_ENDPOINT_URL`, `STORAGE_S3_BUCKET`, `STORAGE_S3_REGION`
  - the access key id and secret key, which go in `.secrets`, never `env.example`
  - `STORAGE_S3_PUBLIC_BASE_URL` for a CDN or R2 custom domain
  - Private files are downloaded via short-lived presigned URLs.
  - It uses the async S3 client library chosen at implementation time. The dependency is added exact-pinned (`agents.md` 5.3).
- **Selection:** `STORAGE_BACKEND=local|s3`, default `local`. Local development of the S3 path uses an optional MinIO Compose profile, like the existing Celery profile, never a mandatory service.

### Key layout

- Images: `public/users/<user_id>/images/<random hex>/<safe filename>` (organizations use the same pattern)
- Documents: `private/...`

Filenames are sanitized, and keys are never taken from user input as-is.

### Image galleries

- **Tables:** `user_images` and `organization_images`. Each row holds:
  - `id` and owner id
  - `storage_key`, `thumbnail_key`
  - `content_type`, `size_bytes`
  - `position` (the gallery order)
  - `created_at`
- **Upload:** it validates the size limit (`STORAGE_IMAGE_MAX_BYTES`, default 5MB) and the type by content (JPEG, PNG or WebP; Pillow must decode it). It then generates a thumbnail, stores both files, and inserts the row.
- **The primary image is the first one** in gallery order (lowest `position`), used as the avatar or logo. There is no separate "primary" flag, so reordering the gallery is how the primary image is changed.
- **Count limit:**
  - A **user** has at most **1** image. It is still stored as an array (the same table and API shape as organizations), so the limit can be raised later without a redesign. The limit of 1 is a named constant, not configuration.
  - An **organization** has at most **n** images, where n comes from `STORAGE_ORGANIZATION_IMAGES_MAX` (default 10), with its own loader test.
  - A user uploading when they already have their one image gets 409; they replace it by deleting the old one first.
- **Deleting and reordering:** an image can be removed from its gallery, and the gallery can be reordered.
- **Who may change a gallery:**
  - A user's gallery: that user, or a platform admin via the role hierarchy (the same rule as plan 12).
  - An organization's gallery: OWNER or ADMIN (the same rule as `UpdateOrganization`).
- **Who may view:** images are public URLs, like apptension's avatars, so they can be shown anywhere without signing.

### Documents

- **Tables:** `user_documents` and `organization_documents`. A document is described by storage-agnostic fields only:
  - `id` and owner id
  - `filename`, the sanitized original name
  - `content_type`, the file type, detected from the content
  - `size_bytes`
  - `storage_key`
  - `uploaded_by_user_id`
  - `created_at`
- **Every document read model includes a `url`,** plus its filename, file type, size, uploader and upload time. The use case asks the `FileStorage` port for the `url`; the entity never stores one, because a presigned URL expires and a local route is deployment-specific.
- **Allowed types:** checked by content: PDF, JPEG, PNG and WebP.
- **Limits:** a size limit (default 10MB) and a count per owner (default 10), matching apptension's defaults, both configurable with loader tests (`agents.md` 2.3).
- **Access:**
  - Documents are private.
  - A user's documents are visible only to that user, as in apptension.
  - For an organization's documents, **only an OWNER or ADMIN may upload or delete** (for now); any member may list and download them.
- **Downloads:** through an authorized route. It streams the file for `local`, or redirects to a short-lived presigned URL for `s3`.

### Consistency between the database and the storage

A file is written to storage before its row is committed. If the commit then fails, the stored file is deleted as a compensating step. On delete, the row is removed first and the file second. A file left behind by a crash is harmless, because nothing references it, and a later cleanup job can remove it. Full two-phase handling is out of scope, and the plan says so rather than pretending otherwise.

## Decisions (confirmed by the human maintainer)

1. **Primary image:** the first image in gallery order. There is no flag.
2. **Image counts:** 1 for a user (a constant), and n for an organization, from `STORAGE_ORGANIZATION_IMAGES_MAX` (default 10).
3. **Size and document limits:** 5MB per image; 10 documents of 10MB each per owner, all configurable.
4. **Organization documents:** only an OWNER or ADMIN uploads or deletes, for now; members read them.
5. **Thumbnails:** one size (256px).
6. **Storage-agnostic domain:** entities and the port carry a key, type and size only. S3, Firebase or disk specifics live in the adapters alone, and every document is returned with a `url` from the port. The port must stay usable by a non-S3 backend such as Google Firebase Storage.

## Proposed changes (each step: test first, confirmed RED, then code, confirmed GREEN)

1. **Settings:** `StorageSettings` with loader tests for every variable.
2. **`FileStorage` port plus `LocalDiskFileStorage`:** adapter tests against a temporary directory.
3. **`S3CompatibleFileStorage`:** integration tests against MinIO in `make test-docker`, via the optional profile.
4. **Content validation and thumbnails:** unit tests with real small JPEG, PNG and WebP files, a real PDF, a renamed text file (rejected), and an oversized file (rejected).
5. **Image-gallery entities, repositories and migrations:** unit and integration tests first.
6. **Gallery commands:** upload, delete and reorder, for users and for organizations, with authorization tests for each.
7. **Document entities, commands and queries:** upload, list, download and delete, with authorization tests.
8. **Routes and DI:** integration tests per route, then the routes and the `CoreProvider` bindings (appended).
9. **Seed data:** a few seeded users and organizations get a small gallery and one PDF, using tiny images stored in the repository for this purpose. Others are left empty.
10. **Docs and release:** wiki pages (storage configuration for AWS S3, Cloudflare R2 and MinIO), `env.example`, and a `CHANGELOG.md` entry with a version bump.

## Verification plan

- `make check` at every GREEN; `make test-docker` for the storage, persistence and route steps, including the S3 path against MinIO.
- Human-driven checks against the seeded data, via Swagger at `/docs`, Postman or `curl`:
  1. Log in as a seeded user and upload a JPEG to your gallery. Open the returned URL in the browser: the image shows.
  2. Upload a `.txt` file renamed to `.jpg`: 400, and nothing is stored.
  3. Reorder the gallery, then list it: the new order is shown.
  4. Upload a PDF to a seeded organization as its ADMIN: the response includes its `url`, file type and size. Download it as a MEMBER: it opens. Try to upload as a MEMBER: 403. Try to download as an outsider: 404.
  5. As a seeded user who already has an image, upload a second one: 409.
  6. Switch `STORAGE_BACKEND=s3` with the MinIO profile, repeat check 1, and see the object in the MinIO console.

## Human checks

(planned -- to run once this plan is implemented; commands follow the routes this plan defines)

Simple checks a human runs by hand against the seeded data (`docs/plans/agents.md` 1.3). The users, passwords and the Avengers come from `scripts/seed_db.py`, and are also listed in `docs/plans/9-organizations.md`'s "Human checks" section.

**What these checks assume, because the plan doesn't fix it yet:**
- **Route paths.** Step 8 decides them. Setup step 4 sets four shell variables to assumed paths that follow the existing routes: `/api/v1/account/...` for the caller's own files, `/api/v1/organizations/{id}/...` for an organization's. If Step 8 picks other paths, change only those four lines.
- **Request and response shapes.** An upload is a multipart `POST` with the form field `file`, answering `201` with the new item's `id` and `url`. A `GET` on the same path lists the items. Document fields are assumed to be named after the table columns: `filename`, `content_type`, `size_bytes`, `uploaded_by_user_id`, `created_at`.
- **The oversize status.** The plan doesn't say which error an over-limit file gets, so check 4 expects a 4xx and nothing stored.
- **Seed data.** Step 9 must leave `wade-wilson` and `matt-murdock` with an empty gallery and no documents. Each check that relies on this proves it first.
- Reordering, deleting, and a platform admin editing another user's gallery are left out until their request shapes are decided.

### Setup

1. In `.secrets`, set `SEED_DB_WITH_TEST_DATA=true`. It's `false` by default in `env.example`.
2. Start from a fresh, freshly seeded database. `db_pg` has no named volume, so `make down` discards the old database:
   ```shell
   make down
   make upd
   ```
3. Create the test files, once. Pillow is a project dependency from Step 4 on, so `uv run python` (run from the repository root) has it:
   ```shell
   uv run python - <<'EOF'
   import os
   from PIL import Image
   Image.new("RGB", (64, 64), "red").save("/tmp/small.jpg", "JPEG")
   Image.new("RGB", (64, 64), "blue").save("/tmp/small.pdf", "PDF")
   # Random pixels barely compress, so this PNG is about 5.9MB: over the 5MB image limit.
   Image.frombytes("RGB", (1400, 1400), os.urandom(1400 * 1400 * 3)).save("/tmp/large.png", "PNG")
   EOF
   echo 'not really an image' > /tmp/fake.jpg
   wc -c /tmp/small.jpg /tmp/small.pdf /tmp/large.png /tmp/fake.jpg
   head -c 5 /tmp/small.pdf; echo
   ```
   Expect `/tmp/large.png` above 5,500,000 bytes, the other three only a few KB or less, and `%PDF-` last.
4. Set the four route variables (assumed paths, see above):
   ```shell
   OWN_IMAGES=http://localhost:8000/api/v1/account/images/
   OWN_DOCUMENTS=http://localhost:8000/api/v1/account/documents/
   ORG_IMAGES=http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/images/
   ORG_DOCUMENTS=http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/documents/
   ```
   Shell variables live only in this terminal, so run everything in it, top to bottom.
5. Each user gets their own cookie file in `/tmp`. A session lasts only **5 minutes** without use (`SessionSettings.TTL_MIN`), so every check logs in each user it acts as, at its own start. An expired cookie gets `401 Not authenticated.`

### Seeded data used (from `scripts/seed_db.py`)

- **Avengers** (`a0000000-0000-4000-8000-000000000001`): `natasha-romanoff` (`BlackWidow!!Red1`) is ADMIN; `peter-parker` (`SpideySense2024!`) is MEMBER.
- `wade-wilson` (`MaximumEffort2024!!!`) belongs to **no** organization: he's the outsider.
- `matt-murdock` (`Daredevil1!!`) isn't in the Avengers either; he has only a pending X-Men invitation.

### Who can do what

- **Your own gallery and documents:** only you change them. Gallery images are public URLs; documents are private to you.
- **An organization's gallery:** OWNER or ADMIN changes it. A MEMBER gets `403`; an outsider gets `404`, as for every organization route.
- **An organization's documents:** OWNER or ADMIN uploads and deletes; any member lists and downloads; an outsider gets `404`.
- **Limits:** a user holds at most 1 image (a second is `409`); an organization at most `STORAGE_ORGANIZATION_IMAGES_MAX` (default 10). Images are JPEG, PNG or WebP up to 5MB; documents are PDF, JPEG, PNG or WebP up to 10MB, 10 per owner. The type is checked by content, so a wrong type is `400` whatever its name.

### Image galleries

1. **Not logged in: 401.**

   **Why:** every upload needs a logged-in user, since a file always has an owner. This command sends no cookie (there's no `-b`), so the server refuses before it looks at the file.

   **Acts on:** no user; the caller's own gallery (`$OWN_IMAGES`). Nothing needs proving: no identity, no state.
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' -X POST "$OWN_IMAGES" -F 'file=@/tmp/small.jpg'
   ```
   Expect `401`.

2. **Upload an image to your own gallery: 201, and its URL opens without logging in.**

   **Why:** a user's gallery holds their picture. Gallery images are public URLs, like avatars elsewhere, so they can be shown anywhere without signing. That's why the fetch below sends no cookie.

   **Acts on:** `wade-wilson`'s own gallery. The new image's URL is saved in `$IMAGE_URL`.

   Log in as `wade-wilson`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
   ```
   Expect `200`. **Prove** his gallery is empty:
   ```shell
   curl -s -b /tmp/wade-wilson.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect no images. Then, as `wade-wilson`, upload the JPEG, and save its URL:
   ```shell
   curl -s -o /tmp/upload.json -w '%{http_code}\n' -b /tmp/wade-wilson.cookies -X POST "$OWN_IMAGES" -F 'file=@/tmp/small.jpg'
   python3 -m json.tool /tmp/upload.json
   IMAGE_URL=$(python3 -c 'import json; print(json.load(open("/tmp/upload.json"))["url"])')
   echo "$IMAGE_URL"
   ```
   Expect `201`, a body with an `id`, a `url` and `content_type` `image/jpeg`, then the URL printed. Fetch it with no cookie:
   ```shell
   curl -s -o /tmp/fetched.jpg -w '%{http_code} %{content_type}\n' "$IMAGE_URL"
   ```
   Expect `200 image/jpeg`. Opening the printed URL in a browser shows a red square. **Prove** the gallery changed:
   ```shell
   curl -s -b /tmp/wade-wilson.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect exactly one image, with the same `url`.

3. **A text file renamed to `.jpg` is caught by its content: 400.**

   **Why:** a file's name is trivially faked, so the type is checked by content: Pillow must be able to decode it. It's `400` because the file itself is invalid, not because of any state or permission.

   **Acts on:** `matt-murdock`'s own gallery.

   Log in as `matt-murdock`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/matt-murdock.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "matt-murdock", "password": "Daredevil1!!"}'
   ```
   Expect `200`. **Prove** his gallery is empty:
   ```shell
   curl -s -b /tmp/matt-murdock.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect no images. Then, as `matt-murdock`, upload the fake, and list the gallery again:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/matt-murdock.cookies -X POST "$OWN_IMAGES" -F 'file=@/tmp/fake.jpg'
   curl -s -b /tmp/matt-murdock.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect `400`, and still no images: nothing was stored.

4. **An image over 5MB is refused.**

   **Why:** the size limit (`STORAGE_IMAGE_MAX_BYTES`, default 5MB) keeps one upload from filling the storage. `/tmp/large.png` is a real PNG, so only its size is wrong. The plan doesn't fix the status, so expect a 4xx (such as `413` or `400`), never `201`.

   **Acts on:** `matt-murdock`'s own gallery.

   Log in as `matt-murdock`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/matt-murdock.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "matt-murdock", "password": "Daredevil1!!"}'
   ```
   Expect `200`. **Prove** his gallery is empty:
   ```shell
   curl -s -b /tmp/matt-murdock.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect no images. Then, as `matt-murdock`, upload the large PNG, and list the gallery again:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/matt-murdock.cookies -X POST "$OWN_IMAGES" -F 'file=@/tmp/large.png'
   curl -s -b /tmp/matt-murdock.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect a 4xx, and still no images.

5. **A user's second image: 409.**

   **Why:** a user holds at most 1 image (a constant, for now). It's `409` and not `400`: the file is valid, and it's the gallery's current state (already full) that blocks it. The user replaces the image by deleting the old one first.

   **Acts on:** `wade-wilson`'s own gallery.

   Log in as `wade-wilson`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
   ```
   Expect `200`. **Prove** his gallery already holds one image:
   ```shell
   curl -s -b /tmp/wade-wilson.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect exactly one image (uploaded in check 2; if the list is empty, check 2 hasn't run). Then, as `wade-wilson`, upload another, and list again:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies -X POST "$OWN_IMAGES" -F 'file=@/tmp/small.jpg'
   curl -s -b /tmp/wade-wilson.cookies "$OWN_IMAGES" | python3 -m json.tool
   ```
   Expect `409`, and still exactly one image.

6. **An organization ADMIN adds to its gallery: 201.**

   **Why:** an organization's gallery is changed by its OWNER or ADMIN, the same rule as updating the organization. The new image goes to the end; the first image stays the primary one (the logo).

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`) gallery.

   Log in as `natasha-romanoff`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
   ```
   Expect `200`. **Prove** she is an ADMIN of the Avengers, and see the gallery as it is now:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   curl -s -b /tmp/natasha-romanoff.cookies "$ORG_IMAGES" | python3 -m json.tool
   ```
   Expect the Avengers with `"role": "admin"`, and note how many images the gallery holds (whatever Step 9 seeded). Then, as `natasha-romanoff`, upload the JPEG, and list again:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X POST "$ORG_IMAGES" -F 'file=@/tmp/small.jpg'
   curl -s -b /tmp/natasha-romanoff.cookies "$ORG_IMAGES" | python3 -m json.tool
   ```
   Expect `201`, and one more image than before, last in the list.

7. **A MEMBER can't change the organization's gallery: 403.**

   **Why:** changing the gallery needs at least ADMIN. It's `403` and not `404` because peter *is* a member: he may know the organization exists, he just isn't allowed to change it.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`) gallery.

   Log in as `peter-parker`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   ```
   Expect `200`. **Prove** he is a MEMBER of the Avengers, and see the gallery as it is now:
   ```shell
   curl -s -b /tmp/peter-parker.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   curl -s -b /tmp/peter-parker.cookies "$ORG_IMAGES" | python3 -m json.tool
   ```
   Expect `peter-parker` with `"role": "member"`, and note the image count. Then, as `peter-parker`, try to upload, and list again:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X POST "$ORG_IMAGES" -F 'file=@/tmp/small.jpg'
   curl -s -b /tmp/peter-parker.cookies "$ORG_IMAGES" | python3 -m json.tool
   ```
   Expect `403`, and the same image count.

8. **An outsider can't change the organization's gallery: 404.**

   **Why:** to anyone outside it, an organization looks like it doesn't exist. A `403` would confirm it exists, so it isn't used.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`) gallery.

   Log in as `wade-wilson`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
   ```
   Expect `200`. **Prove** he belongs to no organization:
   ```shell
   curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   ```
   Expect `"organizations": []` and `"total": 0`. Then, as `wade-wilson`, try to upload to the Avengers' gallery:
   ```shell
   curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies -X POST "$ORG_IMAGES" -F 'file=@/tmp/small.jpg'
   ```
   Expect `404`, with `Organization not found.`

### Documents

9. **An ADMIN uploads a PDF (201, with its details); a MEMBER lists and downloads it (200); an outsider can't download it (404).**

   **Why:** organization documents are uploaded by an OWNER or ADMIN and read by every member. They're private to the organization, so the download `url` checks who's asking. On the default `local` backend it's the app's own authorized route, so an outsider gets the same `404` as for every organization route. (On `s3` it's a short-lived presigned URL instead.) The three users are in one check because they share the one `url` the upload returns.

   **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`) documents. The new document's URL is saved in `$DOC_URL`.

   Log in as `natasha-romanoff`, `peter-parker` and `wade-wilson`:
   ```shell
   curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
   curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
   curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
     -H 'Content-Type: application/json' \
     -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
   ```
   Expect `200` three times. **Prove** the roles, and see the documents as they are now:
   ```shell
   curl -s -b /tmp/natasha-romanoff.cookies \
     http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
   curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
   curl -s -b /tmp/natasha-romanoff.cookies "$ORG_DOCUMENTS" | python3 -m json.tool
   ```
   Expect `natasha-romanoff` as `admin` and `peter-parker` as `member`; `"total": 0` for wade; and note the document count. Then, as `natasha-romanoff`, upload the PDF, and save its URL:
   ```shell
   curl -s -o /tmp/upload.json -w '%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X POST "$ORG_DOCUMENTS" -F 'file=@/tmp/small.pdf'
   python3 -m json.tool /tmp/upload.json
   DOC_URL=$(python3 -c 'import json; print(json.load(open("/tmp/upload.json"))["url"])')
   echo "$DOC_URL"
   ```
   Expect `201`, with a `url`, `"filename": "small.pdf"`, `"content_type": "application/pdf"`, `size_bytes` equal to the `wc -c` size from setup, `uploaded_by_user_id` (natasha's id) and `created_at`. Then, as `peter-parker`, list and download it:
   ```shell
   curl -s -b /tmp/peter-parker.cookies "$ORG_DOCUMENTS" | python3 -m json.tool
   curl -s -L -o /tmp/downloaded.pdf -w '%{http_code}\n' -b /tmp/peter-parker.cookies "$DOC_URL"
   cmp /tmp/small.pdf /tmp/downloaded.pdf && echo same
   ```
   Expect the list one longer, with the new document in it; `200`; then `same`. Then, as `wade-wilson`, try the same URL:
   ```shell
   curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/wade-wilson.cookies "$DOC_URL"
   ```
   Expect `404`.

10. **A MEMBER can't upload an organization document: 403.**

    **Why:** only an OWNER or ADMIN uploads or deletes organization documents, for now. It's `403` and not `404` because peter is a member.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`) documents.

    Log in as `peter-parker`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/peter-parker.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "peter-parker", "password": "SpideySense2024!"}'
    ```
    Expect `200`. **Prove** he is a MEMBER, and see the documents as they are now:
    ```shell
    curl -s -b /tmp/peter-parker.cookies \
      http://localhost:8000/api/v1/organizations/a0000000-0000-4000-8000-000000000001/members/ | python3 -m json.tool
    curl -s -b /tmp/peter-parker.cookies "$ORG_DOCUMENTS" | python3 -m json.tool
    ```
    Expect `peter-parker` with `"role": "member"`, and note the document count. Then, as `peter-parker`, try to upload, and list again:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/peter-parker.cookies -X POST "$ORG_DOCUMENTS" -F 'file=@/tmp/small.pdf'
    curl -s -b /tmp/peter-parker.cookies "$ORG_DOCUMENTS" | python3 -m json.tool
    ```
    Expect `403`, and the same document count.

11. **An outsider can't list the organization's documents: 404.**

    **Why:** the same privacy rule as check 8: an outsider can't learn what an organization holds, or that it exists.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`) documents.

    Log in as `wade-wilson`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
    ```
    Expect `200`. **Prove** he belongs to no organization:
    ```shell
    curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    ```
    Expect `"total": 0`. Then, as `wade-wilson`, try to list the Avengers' documents:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/wade-wilson.cookies "$ORG_DOCUMENTS"
    ```
    Expect `404`, with `Organization not found.`

12. **A disallowed file type is refused by content: 400.**

    **Why:** a document must really be a PDF, JPEG, PNG or WebP. A text file named `report.pdf` doesn't start with `%PDF-`, so its name doesn't help it. natasha is an ADMIN, so the `400` is about the file, not permissions.

    **Acts on:** the Avengers (`a0000000-0000-4000-8000-000000000001`) documents.

    Log in as `natasha-romanoff`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/natasha-romanoff.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "natasha-romanoff", "password": "BlackWidow!!Red1"}'
    ```
    Expect `200`. **Prove** she is an ADMIN, and see the documents as they are now:
    ```shell
    curl -s -b /tmp/natasha-romanoff.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    curl -s -b /tmp/natasha-romanoff.cookies "$ORG_DOCUMENTS" | python3 -m json.tool
    ```
    Expect the Avengers with `"role": "admin"`, and note the document count. Then, as `natasha-romanoff`, upload the text file under a `.pdf` name, and list again:
    ```shell
    curl -s -w '\n%{http_code}\n' -b /tmp/natasha-romanoff.cookies -X POST "$ORG_DOCUMENTS" \
      -F 'file=@/tmp/fake.jpg;filename=report.pdf'
    curl -s -b /tmp/natasha-romanoff.cookies "$ORG_DOCUMENTS" | python3 -m json.tool
    ```
    Expect `400`, and the same document count.

13. **A path-like filename is sanitized (201), and your documents are private to you (404 for anyone else).**

    **Why:** a filename like `../../etc/passwd.pdf` must never steer where a file is stored, so names are sanitized and keys are never taken from user input. A user's documents are visible only to that user, so another user can neither list nor download them. matt gets `404`, not `403`, so he can't even confirm the document exists. The two parts share one check because they share the one `url` the upload returns.

    **Acts on:** `wade-wilson`'s and `matt-murdock`'s own documents. The new document's URL is saved in `$DOC_URL`.

    Log in as `wade-wilson` and `matt-murdock`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
    curl -s -w '\n%{http_code}\n' -c /tmp/matt-murdock.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "matt-murdock", "password": "Daredevil1!!"}'
    ```
    Expect `200` both times. **Prove** both have no documents yet:
    ```shell
    curl -s -b /tmp/wade-wilson.cookies "$OWN_DOCUMENTS" | python3 -m json.tool
    curl -s -b /tmp/matt-murdock.cookies "$OWN_DOCUMENTS" | python3 -m json.tool
    ```
    Expect no documents in either. Then, as `wade-wilson`, upload the PDF under a path-like name, and save its URL:
    ```shell
    curl -s -o /tmp/upload.json -w '%{http_code}\n' -b /tmp/wade-wilson.cookies -X POST "$OWN_DOCUMENTS" \
      -F 'file=@/tmp/small.pdf;filename=../../etc/passwd.pdf'
    python3 -m json.tool /tmp/upload.json
    DOC_URL=$(python3 -c 'import json; print(json.load(open("/tmp/upload.json"))["url"])')
    echo "$DOC_URL"
    ```
    Expect `201`, with a `filename` that has no `../` or `/` in it (for example `passwd.pdf`; the exact sanitized form is the implementation's choice). Then, as `matt-murdock`, list your own documents and try wade's URL:
    ```shell
    curl -s -b /tmp/matt-murdock.cookies "$OWN_DOCUMENTS" | python3 -m json.tool
    curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/matt-murdock.cookies "$DOC_URL"
    ```
    Expect still no documents, then `404` (on the default `local` backend). **Prove** wade's document is there for him:
    ```shell
    curl -s -b /tmp/wade-wilson.cookies "$OWN_DOCUMENTS" | python3 -m json.tool
    ```
    Expect exactly one document, with the sanitized `filename`.

### Configured limit

This check restarts the stack, which reseeds the database, so it comes last.

14. **The organization image limit holds: 201, 201, then 409.**

    **Why:** an organization holds at most `STORAGE_ORGANIZATION_IMAGES_MAX` images (default 10). Setting it to 2 makes the limit quick to reach. A brand-new organization starts with an empty gallery, so the result doesn't depend on what Step 9 seeded. The plan names `409` only for the user limit; this expects the same for the organization limit.

    **Acts on:** a new organization, "Mercs For Money", whose random id is saved in `$ORG_ID`.

    In `.secrets`, add `STORAGE_ORGANIZATION_IMAGES_MAX=2`, then restart so the app reads it:
    ```shell
    make down
    make upd
    ```
    **Prove** the setting is in place:
    ```shell
    grep '^STORAGE_ORGANIZATION_IMAGES_MAX=' .env | tail -1
    ```
    Expect `STORAGE_ORGANIZATION_IMAGES_MAX=2`. Log in as `wade-wilson`:
    ```shell
    curl -s -w '\n%{http_code}\n' -c /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/account/login/ \
      -H 'Content-Type: application/json' \
      -d '{"identifier": "wade-wilson", "password": "MaximumEffort2024!!!"}'
    ```
    Expect `200`. Then, as `wade-wilson`, create the organization, saving its id:
    ```shell
    ORG_ID=$(curl -s -b /tmp/wade-wilson.cookies -X POST http://localhost:8000/api/v1/organizations/ \
      -H 'Content-Type: application/json' -d '{"name": "Mercs For Money"}' \
      | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')
    echo "$ORG_ID"
    ```
    Expect a UUID. A Python `KeyError` traceback means the create failed. **Prove** wade is its OWNER and its gallery is empty (the same assumed path as `$ORG_IMAGES`, for this organization):
    ```shell
    curl -s -b /tmp/wade-wilson.cookies http://localhost:8000/api/v1/organizations/ | python3 -m json.tool
    curl -s -b /tmp/wade-wilson.cookies "http://localhost:8000/api/v1/organizations/$ORG_ID/images/" | python3 -m json.tool
    ```
    Expect "Mercs For Money" with `"role": "owner"`, and no images. Then, as `wade-wilson`, upload three times, and list the gallery:
    ```shell
    for i in 1 2 3; do
      curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/wade-wilson.cookies -X POST \
        "http://localhost:8000/api/v1/organizations/$ORG_ID/images/" -F 'file=@/tmp/small.jpg'
    done
    curl -s -b /tmp/wade-wilson.cookies "http://localhost:8000/api/v1/organizations/$ORG_ID/images/" | python3 -m json.tool
    ```
    Expect `201`, `201`, `409`, then exactly two images. Afterwards, remove the `STORAGE_ORGANIZATION_IMAGES_MAX=2` line from `.secrets`, and restart:
    ```shell
    make down
    make upd
    ```
