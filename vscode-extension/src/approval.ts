/**
 * Tool approval UI — shows VS Code notifications for tool approval requests.
 */

import * as vscode from "vscode";
import type { GatewayClient } from "./gateway-client";
import type { GatewayMessage } from "./protocol";
import { createApprovalResponse } from "./protocol";

// Risk classification for visual styling
const HIGH_RISK_TOOLS = new Set([
  "shell_execute",
  "file_delete",
  "file_move",
  "self_modify_source",
  "crypto_transfer",
  "deploy_website",
  "swarm_spawn",
]);

const READ_ONLY_TOOLS = new Set([
  "file_read",
  "file_list",
  "web_search",
  "knowledge_search",
  "browser_screenshot",
  "skill_read",
  "skill_list",
  "goal_status",
  "identity_status",
  "wallet_status",
  "session_search",
]);

export async function handleApprovalRequest(
  msg: GatewayMessage,
  client: GatewayClient
): Promise<void> {
  const toolName = msg.data.tool_name as string;
  const description = msg.data.description as string;
  const params = msg.data.params as Record<string, unknown>;

  // Format params for display
  const paramLines = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => {
      const val =
        typeof v === "string"
          ? v.length > 100
            ? v.slice(0, 100) + "..."
            : v
          : JSON.stringify(v);
      return `  ${k}: ${val}`;
    })
    .join("\n");

  const detail = paramLines
    ? `${description}\n\n${paramLines}`
    : description;

  // Choose notification level based on risk
  const isHighRisk = HIGH_RISK_TOOLS.has(toolName);
  const isReadOnly = READ_ONLY_TOOLS.has(toolName);

  const prefix = isHighRisk ? "$(warning) " : isReadOnly ? "$(eye) " : "";
  const message = `${prefix}${toolName}: ${description}`;

  const approve = "Approve";
  const deny = "Deny";

  const showFn = isHighRisk
    ? vscode.window.showWarningMessage
    : vscode.window.showInformationMessage;

  const choice = await showFn(message, { detail, modal: false }, approve, deny);

  client.send(createApprovalResponse(msg.id, choice === approve));
}
