import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArtifactResearchDataSource,
  MockResearchDataSource,
} from "../data/adapters";
import type {
  Source,
  Session,
  Brief,
  Gap,
  Profile,
  Diagnostic,
} from "../types";
import type { DemoState } from "../data/demo";
import { restoreDemo } from "../data/demo";
import { z } from "zod";
const adapters = {
  demo: new MockResearchDataSource(),
  artifact: new ArtifactResearchDataSource(),
};
interface WorkspaceValue {
  source: Source;
  setSource: (s: Source) => void;
  sessions: Session[];
  briefs: Brief[];
  gaps: Gap[];
  profiles: Profile[];
  loading: boolean;
  error: string;
  refresh: () => void;
  demo: DemoState | null;
  setDemo: (d: DemoState | null) => void;
  storageNotice: string;
  diagnostics: Diagnostic[];
  snapshotAt?: string;
  sync?: { state: string; message: string; checkedAt?: string };
}
const Context = createContext<WorkspaceValue | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [source, updateSource] = useState<Source>(() => {
    try {
      return sessionStorage.getItem("momentum-source") === "artifact"
        ? "artifact"
        : "demo";
    } catch {
      return "demo";
    }
  });
  const setSource = (s: Source) => {
    updateSource(s);
    try {
      sessionStorage.setItem("momentum-source", s);
    } catch {
      setStorageNotice(
        "Source selection could not be saved; refresh will open Demo.",
      );
    }
  };
  const [storageNotice, setStorageNotice] = useState("");
  const [demo, updateDemo] = useState<DemoState | null>(() => {
    try {
      const v = JSON.parse(
        sessionStorage.getItem("momentum-demo-v1") ?? "null",
      );
      return restoreDemo(v);
    } catch {
      return null;
    }
  });
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["workspace", source],
    queryFn: async () => {
      const a = adapters[source];
      if (a instanceof ArtifactResearchDataSource) return a.loadWorkspace();
      const results = await Promise.allSettled([
        a.listSessions(),
        a.listDailyBriefs(),
        a.listGapLedgerEntries(),
        a.listAgentProfiles(),
      ]);
      const value = <T,>(i: number): T[] =>
        results[i].status === "fulfilled" ? (results[i].value as T[]) : [];
      return {
        sessions: value<Session>(0),
        briefs: value<Brief>(1),
        gaps: value<Gap>(2),
        profiles: value<Profile>(3),
        diagnostics:
          a instanceof ArtifactResearchDataSource ? [...a.diagnostics] : [],
        error: results
          .filter((r) => r.status === "rejected")
          .map((r) => String(r.reason.message ?? r.reason))
          .join(" · "),
        snapshotAt: undefined,
      };
    },
    retry: false,
    refetchInterval: source === "artifact" ? 4000 : false,
  });
  const syncQuery = useQuery({
    queryKey: ["artifact-sync"],
    enabled: source === "artifact",
    refetchInterval: 4000,
    retry: false,
    queryFn: async () => {
      const response = await fetch("/artifacts/sync-status.json", {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Sync health unavailable");
      const status = z
        .object({
          state: z.enum(["ready", "stale", "starting"]),
          message: z.string(),
          checkedAt: z.string(),
        })
        .parse(await response.json());
      if (
        !Number.isFinite(Date.parse(status.checkedAt)) ||
        Date.now() - Date.parse(status.checkedAt) > 15000
      )
        return {
          ...status,
          state: "stale",
          message: "Automatic sync is not responding; showing last snapshot.",
        };
      return status;
    },
  });
  const setDemo = (d: DemoState | null) => {
    updateDemo(d);
    try {
      sessionStorage.setItem("momentum-demo-v1", JSON.stringify(d));
    } catch {
      setStorageNotice(
        "Browser storage is unavailable. This demo will not survive a refresh.",
      );
    }
  };
  const sessions =
    source === "demo" && demo
      ? [
          demo.session,
          ...(query.data?.sessions ?? []).filter(
            (s) => s.id !== demo.session.id,
          ),
        ]
      : (query.data?.sessions ?? []);
  return (
    <Context.Provider
      value={{
        source,
        setSource,
        sessions,
        briefs: query.data?.briefs ?? [],
        gaps: query.data?.gaps ?? [],
        profiles: query.data?.profiles ?? [],
        loading: query.isPending,
        error: query.error
          ? "Snapshot refresh failed; showing last loaded data."
          : (query.data?.error ?? ""),
        refresh: () => {
          void client.invalidateQueries({ queryKey: ["workspace"] });
          void client.invalidateQueries({ queryKey: ["artifact-sync"] });
        },
        demo,
        setDemo,
        storageNotice,
        diagnostics: query.data?.diagnostics ?? [],
        snapshotAt: query.data?.snapshotAt,
        sync:
          source !== "artifact"
            ? undefined
            : syncQuery.error
              ? {
                  state: "stale",
                  message:
                    "Automatic sync unavailable; showing saved snapshot.",
                }
              : syncQuery.data,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useWorkspace() {
  const c = useContext(Context);
  if (!c) throw new Error("WorkspaceProvider required");
  return c;
}
