/**
 * Launch @llmquant/data-mcp with LLMQUANT_API_KEY from project .env
 */
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const envPath = path.join(root, ".env");

function loadDotEnv(filePath) {
  if (!fs.existsSync(filePath)) return;
  for (const raw of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const i = line.indexOf("=");
    const key = line.slice(0, i).trim();
    let value = line.slice(i + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

loadDotEnv(envPath);

if (!process.env.LLMQUANT_API_KEY || !process.env.LLMQUANT_API_KEY.trim()) {
  console.error(
    "[llmquant-data] Missing LLMQUANT_API_KEY in D:\\Cursor\\IGNITE\\AIQuant\\.env"
  );
  process.exit(1);
}

const isWin = process.platform === "win32";
const cmd = isWin ? "npx.cmd" : "npx";
const child = spawn(cmd, ["-y", "@llmquant/data-mcp"], {
  stdio: "inherit",
  env: process.env,
  cwd: root,
  windowsHide: true,
});

child.on("error", (err) => {
  console.error("[llmquant-data] failed to start:", err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
