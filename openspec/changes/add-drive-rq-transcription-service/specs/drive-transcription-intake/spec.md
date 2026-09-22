## Purpose

Define how a submitted Google Drive folder becomes a stable, deduplicated batch of media jobs while validating access and keeping source and destination responsibilities separate.

## ADDED Requirements

### Requirement: Validate source and destination before processing
The system SHALL accept separate source and destination folder references and immutable recognition settings for a batch. It SHALL validate source listing access and destination child-creation capability and, in service-account mode, shared-drive membership before dispatching media jobs. Service-account credentials and user OAuth refresh tokens SHALL remain on the Mac host.

#### Scenario: Readable source with unwritable destination
- **WHEN** the source is readable but the destination is unwritable, or service-account mode targets a folder outside a shared drive
- **THEN** the batch is blocked with an actionable reason and no download or inference starts

#### Scenario: Private My Drive source and shared-drive destination
- **WHEN** the service account can read the source and the destination passes validation
- **THEN** the batch is accepted without requiring the source to be in a shared drive

### Requirement: Recursively enumerate supported media
The system SHALL scan every page of the submitted folder tree, deduplicate visited folder IDs, exclude trashed items, shortcuts and the result subtree, and report unsupported items as skipped. It SHALL reject destination layouts that exclude the source itself. Inference SHALL NOT block unrelated scan requests.

#### Scenario: Nested paginated source
- **WHEN** supported media occur across multiple nested folders and list pages
- **THEN** each eligible file is discovered and its relative path is retained

#### Scenario: Partial scan failure
- **WHEN** a folder cannot be listed after bounded retries
- **THEN** the scan is reported incomplete and its new candidates are not dispatched as a successfully scanned batch

#### Scenario: Outputs inside the source tree
- **WHEN** the destination is a dedicated descendant of the source
- **THEN** the destination subtree is excluded from discovery

### Requirement: Identify source versions and deduplicate submissions
The system SHALL identify jobs by source ID, content identity, processing settings and destination identity. Repeated discovery of the same identity SHALL reuse the job record. It SHALL prefer content checksums over metadata-only changes and verify the downloaded version before inference.

#### Scenario: Rename without content change
- **WHEN** a file retains the same ID and checksum but changes name
- **THEN** a rescan does not create a new transcription

#### Scenario: Source changes during download
- **WHEN** downloaded bytes or post-download metadata do not match the scheduled source version
- **THEN** those bytes are not transcribed under the old version and the source is reconciled for a new job

#### Scenario: Same name with different file IDs
- **WHEN** two source files have the same name but distinct IDs
- **THEN** their identities and delivery mappings remain distinguishable

### Requirement: Publish stable scan batches
The system SHALL publish new jobs after a successful scan in natural relative-path order, support explicit rescanning, and permit optional periodic rescanning without duplicating unchanged jobs.

#### Scenario: Rescan after new upload
- **WHEN** an unchanged folder gains one eligible media file and is rescanned
- **THEN** one new job is created while existing job records are reused

### Requirement: Support explicit user OAuth credentials
The system SHALL permit native user OAuth for My Drive destinations with child-creation capability, keep service-account mode available, and never silently fall back between identities. Initial authorization SHALL use a Desktop OAuth client with PKCE and a loopback callback. Refresh tokens SHALL be stored atomically with owner-only access outside synchronized directories. Revoked or expired user authorization SHALL block processing with a redacted actionable message.

#### Scenario: User authorizes a My Drive destination
- **WHEN** user OAuth credentials are configured and the destination allows child creation
- **THEN** absence of shared-drive membership does not block the batch

#### Scenario: Offline authorization expires
- **WHEN** Google refuses to refresh the user's authorization
- **THEN** no service-account fallback occurs and the operator is asked to authorize again without exposing credentials
