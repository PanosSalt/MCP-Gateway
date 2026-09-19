# Filesystem Tools

MCP Gateway can expose sandboxed filesystem access as MCP tools. When enabled, AI assistants can read, search, and (for admins) write files within designated directories.

Filesystem tools are disabled by default and only appear when `FILESYSTEM_ALLOWED_DIRS` is configured.

---

## Configuration

Set the `FILESYSTEM_ALLOWED_DIRS` environment variable to a comma-separated list of directories:

```bash
# .env
FILESYSTEM_ALLOWED_DIRS=/data,/projects
```

When empty or unset, no filesystem tools are exposed.

### Docker volume mounts

To give the gateway access to host directories, mount them as Docker volumes and reference the container paths:

```yaml
# docker-compose.yml
services:
  api:
    volumes:
      - /home/user/data:/data:ro
      - /home/user/projects:/projects
    environment:
      - FILESYSTEM_ALLOWED_DIRS=/data,/projects
```

Use `:ro` (read-only) for directories that should not be writable even by admin users.

> The shipped `docker-compose.yml` mounts `./data:/data` and `./projects:/projects`
> **read-write**, without `:ro`. If you enable the write tools and want a mount to
> stay read-only, add `:ro` yourself — the gateway's role checks do not make the
> filesystem read-only, the mount flag does.

---

## Security Model

All filesystem operations are restricted to the configured allowed directories:

- Every path argument is resolved to an absolute path via `os.path.realpath()`
- The resolved path must either **equal** an allowed directory or begin with it
  followed by a path separator. The separator matters: it is what stops
  `/data-evil` from passing a check for `/data`
- Symlinks are resolved before validation, preventing symlink escapes
- Path traversal (`../`) is blocked by the realpath resolution
- Entries in `FILESYSTEM_ALLOWED_DIRS` must be absolute and free of `..`, or the
  gateway refuses to start

If a path is outside the allowed directories, the tool returns an error and the operation is denied.

### Role requirements

| Operation | Default Minimum Role |
|-----------|---------------------|
| Read operations | `analyst` |
| Write operations | `admin` |

Admins can override these defaults per-tool via the [tool role overrides](tool-role-overrides.md) system.

---

## Available Tools

### Read Operations (analyst+)

#### `fs_read_file`

Read a file and return its contents as UTF-8 text.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the file |

Returns the file contents as text. Binary files will produce encoding errors.

Files larger than **10 MB** are refused with an error rather than read.

#### `fs_list_directory`

List the contents of a directory with type indicators.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the directory |

Returns entries prefixed with `[FILE]` or `[DIR]`, one per line, sorted by name:
```
[DIR] reports
[FILE] README.md
[FILE] summary.csv
```

Names carry no trailing slash. An empty directory returns the literal string
`(empty directory)`.

#### `fs_directory_tree`

Recursively list the directory structure as JSON.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the root directory |
| `max_depth` | integer | No | Maximum recursion depth (default: 5, hard cap 10) |

Returns a JSON tree with names, types, and children. Values above 10 are
silently clamped to 10. Directories that cannot be read are skipped rather than
raising.

#### `fs_search_files`

Search for files matching a glob pattern.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Directory to search in |
| `pattern` | string | Yes | Glob pattern (e.g. `*.csv`, `**/*.json`) |

Returns newline-separated matching paths, or `No matches found.` when there are
none.

Two behaviours worth knowing: the pattern is matched against **directory names
as well as file names**, so directories appear in the results; and the search
stops after roughly 1000 matches, so a broad pattern returns a truncated list
with no indication that it was cut short.

#### `fs_get_file_info`

Get metadata about a file or directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the file |

Returns a JSON object with `path`, `type` (`file` or `directory`), `size_bytes`,
`created`, `modified`, `accessed` and `permissions`.

`permissions` is the octal `st_mode`. If the sandbox contains files whose
mode you would rather not expose to tool callers, restrict this tool with a
per-tool role override.

### Write Operations (admin only)

#### `fs_write_file`

Create or overwrite a file with the given content.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the file |
| `content` | string | Yes | Text content to write |

Creates parent directories if they don't exist. Overwrites the file if it already exists.

#### `fs_create_directory`

Create a directory, including any missing parent directories.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the directory |

#### `fs_move_file`

Move or rename a file or directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source` | string | Yes | Current path |
| `destination` | string | Yes | New path |

Both source and destination must be within allowed directories.

This is **not** an overwrite: if the destination already exists the call fails
with `Destination already exists`. Delete or move the existing entry first.

---

## Audit Trail

All filesystem tool invocations are logged to the audit trail:

| Event | When |
|-------|------|
| `fs.fs_read_file` | File read successfully |
| `fs.fs_write_file` | File written successfully |
| `fs.fs_read_file.error` | Read failed (permission, not found, etc.) |
| `fs.fs_write_file.error` | Write failed |

The same pattern applies to all other filesystem tools (`fs.fs_list_directory`, `fs.fs_create_directory`, etc.). A `fs.{tool}.denied` event is written when the caller's role is below the tool's minimum.

Metadata is `{"tool": ..., "args": {...}}`. Within `args`:

- Path arguments appear twice — as supplied (`path`) and as resolved
  (`path_resolved`). Audit against the resolved form; it reflects the real
  target after symlink resolution.
- `content` is never recorded, only its length as `"<N chars>"`.
- Error entries add an `error` key and still carry the attempted path, so a
  blocked traversal shows which path was tried.

See [audit-logging.md](audit-logging.md) for the full event catalogue.
