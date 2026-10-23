import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { Envelope, Location, Program, Reward } from "./types";

export function useLocations() {
  return useQuery({
    queryKey: ["locations"],
    queryFn: async () => (await api<Envelope<Location[]>>("/locations")).data,
  });
}

/** Active locations the current user may act at. */
export function useAccessibleLocations() {
  const q = useLocations();
  const data = (q.data ?? []).filter((l) => l.status === "active" && l.accessible !== false);
  return { ...q, data };
}

export function useProgram() {
  return useQuery({
    queryKey: ["program"],
    queryFn: async () => (await api<Envelope<Program>>("/programs/current")).data,
  });
}

export function useRewards(status?: string) {
  return useQuery({
    queryKey: ["rewards", status ?? "all"],
    queryFn: async () => (await api<Envelope<Reward[]>>(`/rewards${status ? `?status=${status}` : ""}`)).data,
  });
}

const LOCATION_KEY = "loyalloop.location";

/** Remember the last-used checkout location on this device (non-sensitive convenience). */
export function rememberedLocation(): number | null {
  try {
    const v = window.localStorage.getItem(LOCATION_KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export function rememberLocation(id: number) {
  try {
    window.localStorage.setItem(LOCATION_KEY, String(id));
  } catch {
    /* storage unavailable */
  }
}
