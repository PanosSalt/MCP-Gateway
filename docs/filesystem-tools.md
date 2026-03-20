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

---

## Security Model

All filesystem operations are restricted to the configured allowed directories:

- Every path argument is resolved to an absolute path via `os.path.realpath()`
- The resolved path must start with one of the allowed directories
- Symlinks are resolved before validation, preventing symlink escapes
- Path traversal (`../`) is blocked by the realpath resolution

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

#### `fs_list_directory`

List the contents of a directory with type indicators.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the directory |

Returns entries prefixed with `[FILE]` or `[DIR]`:
```
[DIR]  reports/
[FILE] summary.csv
[FILE] README.md
```

#### `fs_directory_tree`

Recursively list the directory structure as JSON.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the root directory |
| `max_depth` | integer | No | Maximum recursion depth (default: 5) |

Returns a JSON tree with names, types, and children.

#### `fs_search_files`

Search for files matching a glob pattern.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Directory to search in |
| `pattern` | string | Yes | Glob pattern (e.g. `*.csv`, `**/*.json`) |

Returns a list of matching file paths.

#### `fs_get_file_info`

Get metadata about a file or directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Absolute path to the file |

Returns size (bytes), creation time, modification time, and whether it is a file or directory.

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

---

## Audit Trail

All filesystem tool invocations are logged to the audit trail:

| Event | When |
|-------|------|
| `fs.fs_read_file` | File read successfully |
| `fs.fs_write_file` | File written successfully |
| `fs.fs_read_file.error` | Read failed (permission, not found, etc.) |
| `fs.fs_write_file.error` | Write failed |

The same pattern applies to all other filesystem tools (`fs.fs_list_directory`, `fs.fs_create_directory`, etc.).

Metadata includes the path, and for errors, the error message.
