# File Management

## Description

Complete guide for creating, reading, editing, organizing, deleting, and moving files on the user's system — covering all six file tools, shell integration, backup strategies, and protected file awareness.

## Triggers

- create file
- write file
- edit file
- delete file
- move file
- rename
- organize files
- backup
- copy
- find files
- search files
- directory
- folder
- cleanup
- disk space

## Instructions

### 1. Tool Selection

EloPhanto has six dedicated file tools. Use the right one:

| Task | Tool | Permission Level |
|---|---|---|
| Read a file | file_read | SAFE |
| List directory contents | file_list | SAFE |
| Create or overwrite a file | file_write | MODERATE |
| Move or rename | file_move | MODERATE |
| Delete | file_delete | DESTRUCTIVE |
| Complex operations (pipes, bulk) | shell_execute | DESTRUCTIVE |

**Rule:** Always prefer dedicated file tools over shell_execute. Only use
shell_execute for operations that need shell features (pipes, globbing,
find + exec, xargs, etc.).

### 2. Reading Files

#### Simple Read
```
file_read(path="/path/to/file.txt")
→ returns: content, size_bytes, line_count
```

#### Targeted Read (Large Files)
```
file_read(path="/path/to/large.log", start_line=100, end_line=150)
→ returns only lines 100-150
```

**When to use line ranges:**
- File is larger than ~1000 lines
- You know the section you need (e.g., config block, function definition)
- You've already read the file once and need to re-read a specific section

**When to use full read:**
- File is small/medium (under 1000 lines)
- You need to understand the full context
- First time reading the file

### 3. Listing Directories

#### Basic Listing
```
file_list(path="/home/user/projects")
→ returns entries with name, path, type, size, modified date
```

#### Recursive with Pattern
```
file_list(path="/home/user/project", recursive=true, pattern="*.py")
→ finds all Python files in the project tree
```

#### Including Hidden Files
```
file_list(path="/home/user", include_hidden=true)
→ includes .dotfiles and .directories
```

**Strategy for finding files:**
1. Start with file_list in the likely parent directory
2. If not found, widen with recursive=true
3. If you know the extension, use pattern filtering
4. For complex searches (regex, content-based), use shell_execute with find/grep

### 4. Writing Files

#### New File
```
file_write(path="/path/to/new_file.py", content="...")
→ Creates parent directories automatically
→ Returns: path, size_bytes
```

#### Overwriting (With Backup)
```
file_write(path="/path/to/existing.txt", content="new content")
→ Creates .bak backup of the original automatically
→ Returns: path, size_bytes, backed_up=true
```

#### Overwriting (No Backup)
```
file_write(path="/path/to/temp.txt", content="data", backup=false)
→ Overwrites without creating .bak
```

**Best practices:**
- Always read a file before overwriting it — understand what you're replacing
- For small edits to large files, read the file, modify the content in your
  reasoning, then write the complete file back
- Use backup=true (default) for important files, backup=false for temp/generated files
- create_directories=true (default) creates parent dirs — no need to mkdir first

### 5. Moving and Renaming

#### Rename a File
```
file_move(source="/path/to/old_name.txt", destination="/path/to/new_name.txt")
```

#### Move to Different Directory
```
file_move(source="/path/to/file.txt", destination="/new/location/file.txt")
→ Creates /new/location/ if it doesn't exist
```

#### Overwrite Destination
```
file_move(source="/path/to/new.txt", destination="/path/to/existing.txt", overwrite=true)
→ Replaces the destination
```

**Caution:** Moving a file with overwrite=true permanently replaces the
destination. There's no .bak backup for moves.

### 6. Deleting Files

#### Delete a Single File
```
file_delete(path="/path/to/file.txt")
→ Returns: deleted path, type, size_bytes
```

#### Delete an Empty Directory
```
file_delete(path="/path/to/empty_dir")
→ Fails if directory is not empty
```

#### Delete a Directory with Contents
```
file_delete(path="/path/to/dir", recursive=true)
→ Deletes everything inside, then the directory itself
→ THIS IS IRREVERSIBLE — confirm with user first
```

**Safety rules:**
- Never delete with recursive=true without confirming with the user
- Check what's in a directory (file_list) before deleting it
- Protected files (core/executor.py, core/vault.py, etc.) cannot be deleted

### 7. Protected Files

The following files are protected and CANNOT be modified, moved, or deleted
by any tool:

- core/protected.py
- core/executor.py
- core/vault.py
- core/config.py
- core/registry.py
- core/log_setup.py
- permissions.yaml

If a task requires changing these files, explain to the user what change
is needed and let them make it manually.

### 8. Shell Integration for Complex Operations

Use shell_execute when dedicated file tools aren't enough:

#### Bulk Operations
```
shell_execute(command="find /path -name '*.log' -mtime +30 -delete")
→ Delete all .log files older than 30 days
```

#### Content Search
```
shell_execute(command="grep -r 'TODO' /path/to/project --include='*.py'")
→ Find all TODO comments in Python files
```

#### Disk Usage
```
shell_execute(command="du -sh /path/to/dir/*")
→ Size of each subdirectory
```

#### File Comparison
```
shell_execute(command="diff /path/to/file1 /path/to/file2")
→ Show differences between two files
```

#### Permissions
```
shell_execute(command="chmod 755 /path/to/script.sh")
→ Make a script executable
```

### 9. Common Patterns

#### Safe File Update
```
1. file_read the original
2. Modify content in your reasoning
3. file_write with backup=true
4. file_read again to verify the write succeeded
```

#### Directory Organization
```
1. file_list(recursive=true) to understand current structure
2. Plan the reorganization
3. Create destination directories (file_write auto-creates parents)
4. file_move each file to its new location
5. file_delete empty source directories
6. file_list to verify the result
```

#### Cleanup / Free Disk Space
```
1. shell_execute(command="du -sh /path/*") to find large directories
2. file_list with pattern to identify deletable files (logs, caches, temp)
3. Confirm the plan with the user
4. file_delete each target (or shell_execute for bulk)
5. shell_execute(command="df -h") to confirm space recovered
```

## Notes

All file paths can be absolute or relative to the project root. The ~ character
is expanded to the user's home directory. The agent operates with the same
filesystem permissions as the user who started it.
