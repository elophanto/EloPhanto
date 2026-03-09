/**
 * Status bar item — shows connection status, agent state, and mind status.
 */

import * as vscode from "vscode";

export class StatusBar {
  private item: vscode.StatusBarItem;

  constructor() {
    this.item = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      100
    );
    this.item.command = "elophanto.chat.focus";
    this.setDisconnected();
    this.item.show();
  }

  setConnected(): void {
    this.item.text = "$(hubot) EloPhanto";
    this.item.tooltip = "Connected to EloPhanto gateway";
    this.item.backgroundColor = undefined;
  }

  setDisconnected(): void {
    this.item.text = "$(hubot) EloPhanto $(circle-slash)";
    this.item.tooltip = "Disconnected — click to open chat";
    this.item.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
  }

  setReconnecting(): void {
    this.item.text = "$(hubot) EloPhanto $(sync~spin)";
    this.item.tooltip = "Reconnecting to gateway...";
    this.item.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
  }

  setThinking(): void {
    this.item.text = "$(hubot) EloPhanto $(loading~spin)";
    this.item.tooltip = "Agent is thinking...";
    this.item.backgroundColor = undefined;
  }

  setIdle(): void {
    this.setConnected();
  }

  dispose(): void {
    this.item.dispose();
  }
}
