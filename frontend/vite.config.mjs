import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFile, realpath } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { controlProxy } from "./scripts/control_proxy.mjs";

const root = path.dirname(fileURLToPath(import.meta.url));
function artifactFiles() {
  return {
    name: "read-only-artifact-files",
    configureServer(server) {
      const watcher = spawn(
        "python3",
        [path.join(root, "scripts/artifact_watch.py")],
        {
          cwd: root,
          stdio: ["ignore", "ignore", "inherit"],
        },
      );
      watcher.on("error", () =>
        server.config.logger.warn(
          "Artifact sync could not start; last snapshot remains available.",
        ),
      );
      const stop = () => {
        watcher.kill("SIGTERM");
        process.off("exit", stop);
      };
      process.once("exit", stop);
      server.httpServer?.once("close", stop);
      server.middlewares.use("/artifacts", async (req, res) => {
        if (req.method !== "GET") {
          res.statusCode = 405;
          res.end();
          return;
        }
        const relative = (req.url || "").split("?")[0].replace(/^\//, "");
        if (
          relative !== "index.json" &&
          relative !== "sync-status.json" &&
          !/^snapshots\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_.-]+\.json$/.test(relative)
        ) {
          res.statusCode = 404;
          res.end();
          return;
        }
        try {
          const base = await realpath(path.join(root, ".generated/artifacts"));
          const file = await realpath(path.join(base, relative));
          if (!file.startsWith(base + path.sep))
            throw new Error("Invalid path");
          const data = await readFile(file);
          res.setHeader("Content-Type", "application/json");
          res.setHeader("Cache-Control", "no-store");
          res.end(data);
        } catch {
          res.statusCode = 404;
          res.end(JSON.stringify({ error: "Snapshot unavailable" }));
        }
      });
    },
  };
}

export default defineConfig({
  build: {
    outDir: "dist/client",
  },
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    fs: { deny: [".env", ".env.*", "*.{crt,pem}", "**/.git/**", "**/connection.json", "**/state.json", "**/momentum-ui/**", "**/.generated/control/**", "**/reports/**"] },
    host: "127.0.0.1",
    allowedHosts: ["terminal.local"],
    warmup: {
      clientFiles: ["./src/main.tsx"],
    },
  },
  plugins: [react(), tailwindcss(), artifactFiles(), controlProxy(root)],
});
