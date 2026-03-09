/**
 * EloPhanto VS Code Extension — connects to the EloPhanto gateway
 * as another channel adapter, providing IDE-integrated chat, tool approval,
 * and context injection.
 */

import * as vscode from "vscode";
import { GatewayClient } from "./gateway-client";
import { ChatProvider } from "./chat-provider";
import { StatusBar } from "./status-bar";
import { handleApprovalRequest } from "./approval";
import { ensureGateway, disposeGateway } from "./launcher";
import {
  MessageType,
  createCommandMessage,
} from "./protocol";

let client: GatewayClient;
let statusBar: StatusBar;
let chatProvider: ChatProvider;

export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration("elophanto");
  const gatewayUrl = config.get<string>("gatewayUrl", "ws://127.0.0.1:18789");

  // Create gateway client
  client = new GatewayClient(gatewayUrl);

  // Create status bar
  statusBar = new StatusBar();
  context.subscriptions.push({ dispose: () => statusBar.dispose() });

  // Create chat provider
  chatProvider = new ChatProvider(context.extensionUri, client);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatProvider.viewType, chatProvider)
  );

  // Gateway event handlers
  client.on(MessageType.STATUS, (msg) => {
    const status = msg.data.status as string;
    switch (status) {
      case "connected":
        statusBar.setConnected();
        break;
      case "disconnected":
        statusBar.setDisconnected();
        break;
      case "reconnecting":
        statusBar.setReconnecting();
        break;
    }
  });

  client.on(MessageType.RESPONSE, (msg) => {
    if (msg.data.done) {
      statusBar.setIdle();
    } else {
      statusBar.setThinking();
    }
  });

  client.on(MessageType.APPROVAL_REQUEST, (msg) => {
    handleApprovalRequest(msg, client);
  });

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand("elophanto.connect", () => {
      client.connect();
      vscode.window.showInformationMessage("Connecting to EloPhanto gateway...");
    }),

    vscode.commands.registerCommand("elophanto.disconnect", () => {
      client.disconnect();
      statusBar.setDisconnected();
      vscode.window.showInformationMessage("Disconnected from EloPhanto.");
    }),

    vscode.commands.registerCommand("elophanto.sendSelection", () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.selection.isEmpty) {
        vscode.window.showWarningMessage("No text selected.");
        return;
      }
      const text = editor.document.getText(editor.selection);
      chatProvider.sendMessage(text, true);
    }),

    vscode.commands.registerCommand("elophanto.explain", () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.selection.isEmpty) {
        vscode.window.showWarningMessage("No text selected.");
        return;
      }
      const text = editor.document.getText(editor.selection);
      const prompt = `Explain this code:\n\n\`\`\`${editor.document.languageId}\n${text}\n\`\`\``;
      chatProvider.sendMessage(prompt, true);
    }),

    vscode.commands.registerCommand("elophanto.fix", () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.selection.isEmpty) {
        vscode.window.showWarningMessage("No text selected.");
        return;
      }
      const text = editor.document.getText(editor.selection);
      const diagnostics = vscode.languages
        .getDiagnostics(editor.document.uri)
        .filter(
          (d) =>
            d.range.intersection(editor.selection) !== undefined &&
            (d.severity === vscode.DiagnosticSeverity.Error ||
              d.severity === vscode.DiagnosticSeverity.Warning)
        );

      let prompt = `Fix this code:\n\n\`\`\`${editor.document.languageId}\n${text}\n\`\`\``;
      if (diagnostics.length > 0) {
        const errors = diagnostics
          .map(
            (d) =>
              `Line ${d.range.start.line + 1}: ${
                d.severity === vscode.DiagnosticSeverity.Error
                  ? "ERROR"
                  : "WARNING"
              } — ${d.message}`
          )
          .join("\n");
        prompt += `\n\nEditor diagnostics:\n${errors}`;
      }
      chatProvider.sendMessage(prompt, true);
    }),

    vscode.commands.registerCommand("elophanto.newChat", () => {
      chatProvider.newChat();
    }),

    vscode.commands.registerCommand("elophanto.stop", () => {
      client.send(createCommandMessage("stop"));
    }),

    vscode.commands.registerCommand("elophanto.mind", () => {
      client.send(createCommandMessage("mind_status"));
    })
  );

  // Auto-connect: check if gateway is running, offer to start if not
  if (config.get<boolean>("autoConnect", true)) {
    ensureGateway().then(() => {
      client.connect();
    });
  }

  // Cleanup
  context.subscriptions.push({
    dispose: () => {
      client.dispose();
      disposeGateway();
    },
  });

  // Watch for config changes — full reload on URL change
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("elophanto.gatewayUrl")) {
        vscode.commands.executeCommand("workbench.action.reloadWindow");
      }
    })
  );
}

export function deactivate(): void {
  client?.dispose();
  statusBar?.dispose();
}
