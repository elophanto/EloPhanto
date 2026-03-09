/**
 * IDE context collection — gathers active file, selection, diagnostics
 * to send alongside chat messages so the agent knows what the user is looking at.
 */

import * as vscode from "vscode";
import type { IdeContext } from "./protocol";

export function collectIdeContext(): IdeContext | undefined {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return undefined;

  const ctx: IdeContext = {};

  // Active file (relative to workspace)
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (workspaceFolder) {
    ctx.workspace_root = workspaceFolder.uri.fsPath;
    ctx.active_file = vscode.workspace.asRelativePath(editor.document.uri);
  } else {
    ctx.active_file = editor.document.uri.fsPath;
  }

  // Language
  ctx.language = editor.document.languageId;

  // Selection (if any)
  const selection = editor.selection;
  if (!selection.isEmpty) {
    ctx.selection = {
      text: editor.document.getText(selection),
      start_line: selection.start.line + 1,
      end_line: selection.end.line + 1,
    };
  }

  // Open files
  ctx.open_files = vscode.window.tabGroups.all
    .flatMap((group) => group.tabs)
    .map((tab) => {
      const input = tab.input;
      if (input && typeof input === "object" && "uri" in input) {
        const uri = (input as { uri: vscode.Uri }).uri;
        return workspaceFolder
          ? vscode.workspace.asRelativePath(uri)
          : uri.fsPath;
      }
      return null;
    })
    .filter((f): f is string => f !== null)
    .slice(0, 10); // Cap at 10 files

  // Diagnostics for the active file (errors + warnings)
  const diagnostics = vscode.languages
    .getDiagnostics(editor.document.uri)
    .filter(
      (d) =>
        d.severity === vscode.DiagnosticSeverity.Error ||
        d.severity === vscode.DiagnosticSeverity.Warning
    )
    .slice(0, 10) // Cap at 10 diagnostics
    .map((d) => ({
      file: ctx.active_file!,
      line: d.range.start.line + 1,
      severity:
        d.severity === vscode.DiagnosticSeverity.Error ? "error" : "warning",
      message: d.message,
    }));

  if (diagnostics.length > 0) {
    ctx.diagnostics = diagnostics;
  }

  return ctx;
}
