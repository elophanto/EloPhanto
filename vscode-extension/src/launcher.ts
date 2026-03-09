/**
 * Gateway checker — detects if gateway is running.
 * Does NOT auto-launch (user must start manually for vault password entry).
 */

import * as vscode from "vscode";
import * as net from "net";

/**
 * Check if the gateway is listening on the given port.
 */
export function isGatewayRunning(port: number = 18789): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(1000);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => {
      socket.destroy();
      resolve(false);
    });
    socket.connect(port, "127.0.0.1");
  });
}

/**
 * Check if gateway is running. If not, show a message telling the user to start it.
 */
export async function ensureGateway(): Promise<void> {
  const url = vscode.workspace
    .getConfiguration("elophanto")
    .get<string>("gatewayUrl", "ws://127.0.0.1:18789");
  const match = url.match(/:(\d+)/);
  const port = match ? parseInt(match[1], 10) : 18789;

  if (await isGatewayRunning(port)) {
    return;
  }

  vscode.window.showWarningMessage(
    "EloPhanto gateway is not running. Start it in a terminal: ./start.sh",
    "OK"
  );
}

export function disposeGateway(): void {
  // No-op — we don't manage the gateway process
}
