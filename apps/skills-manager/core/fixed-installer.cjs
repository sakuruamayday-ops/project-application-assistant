const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");
const AdmZip = require("adm-zip");
const { safeRelativePath, timestampId } = require("./paths.cjs");

function workBuddyRunning(platform = process.platform) {
  if (platform === "darwin") {
    return spawnSync("pgrep", ["-x", "WorkBuddy"], { windowsHide: true }).status === 0;
  }
  if (platform === "win32") {
    const result = spawnSync("tasklist.exe", ["/FI", "IMAGENAME eq WorkBuddy.exe", "/NH"], {
      encoding: "utf8",
      windowsHide: true,
    });
    return result.status === 0 && /WorkBuddy\.exe/i.test(result.stdout || "");
  }
  return false;
}

function stageFixedInstaller({ archivePath, cacheRoot, platform = process.platform }) {
  const launcher = platform === "win32"
    ? "install-jiaotang-workbuddy.cmd"
    : "install-jiaotang-workbuddy.command";
  const zip = new AdmZip(archivePath);
  const launcherEntry = zip.getEntries().find((entry) => entry.entryName.endsWith(`/${launcher}`));
  if (!launcherEntry) throw new Error(`签名包没有固定安装器 ${launcher}`);
  const packageRoot = launcherEntry.entryName.slice(0, -launcher.length).replace(/\/+$/, "");
  const stageRoot = path.join(cacheRoot, "installers", `${timestampId()}-${platform}`);
  for (const entry of zip.getEntries()) {
    if (entry.isDirectory || !entry.entryName.startsWith(`${packageRoot}/`)) continue;
    const relative = safeRelativePath(entry.entryName.slice(packageRoot.length + 1));
    const destination = path.join(stageRoot, ...relative.split("/"));
    fs.mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
    fs.writeFileSync(destination, entry.getData(), { mode: relative.endsWith(".command") ? 0o700 : 0o600 });
  }
  return {
    stageRoot,
    launcher: path.join(stageRoot, launcher),
    platform,
  };
}

function launchFixedInstaller(staged, platform = process.platform) {
  if (workBuddyRunning(platform)) {
    throw new Error("WorkBuddy 仍在运行。请完全退出后再启动固定安装器。");
  }
  if (!fs.existsSync(staged.launcher)) throw new Error("固定安装器暂存文件不存在");
  if (platform === "darwin") {
    const child = spawn("open", ["-a", "Terminal", staged.launcher], {
      detached: true,
      stdio: "ignore",
    });
    child.unref();
  } else if (platform === "win32") {
    const child = spawn("cmd.exe", ["/c", "start", "", "cmd.exe", "/k", staged.launcher], {
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    child.unref();
  } else {
    throw new Error(`当前系统不支持 WorkBuddy 固定安装器：${platform}`);
  }
  return {
    status: "launched",
    launcher: staged.launcher,
    host: os.hostname(),
  };
}

module.exports = {
  workBuddyRunning,
  stageFixedInstaller,
  launchFixedInstaller,
};
