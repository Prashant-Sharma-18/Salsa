import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { MapPin, Plus } from "lucide-react";
import { api } from "../api/client";
import { useLocations } from "../api/hooks";
import type { Location } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, applyServerErrors, Button, Card, EmptyState, Modal, PageHeader, QueryState, Status, TextInput } from "../components/ui";

const schema = z.object({ name: z.string().trim().min(1, "Required").max(120), address: z.string().max(255) });

export function LocationsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const locations = useLocations();
  const [editing, setEditing] = useState<Location | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const manage = can("locations.manage");

  async function toggleArchive(loc: Location) {
    setError(null);
    try {
      await api(`/locations/${loc.id}`, { method: "PATCH", body: { status: loc.status === "active" ? "archived" : "active" } });
      qc.invalidateQueries({ queryKey: ["locations"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  return (
    <>
      <PageHeader
        title="Locations"
        description="Purchases, redemptions and staff access are tracked per location."
        actions={
          manage && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              <Plus size={16} aria-hidden="true" /> Add location
            </Button>
          )
        }
      />
      {error && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind="error">{error}</Alert>
        </div>
      )}
      <Card bodyless>
        <QueryState isLoading={locations.isLoading} error={locations.error}>
          {locations.data?.length === 0 ? (
            <EmptyState icon={<MapPin size={28} aria-hidden="true" />} title="No locations" />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Address</th>
                    <th>Status</th>
                    <th>Your access</th>
                    {manage && <th><span className="visually-hidden">Actions</span></th>}
                  </tr>
                </thead>
                <tbody>
                  {locations.data?.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <strong>{l.name}</strong>
                      </td>
                      <td className="small">{l.address || "—"}</td>
                      <td>
                        <Status value={l.status} />
                      </td>
                      <td className="small">{l.accessible ? "Yes" : "No"}</td>
                      {manage && (
                        <td className="num">
                          <div className="row" style={{ justifyContent: "flex-end" }}>
                            <Button size="sm" onClick={() => setEditing(l)}>
                              Edit
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => toggleArchive(l)}>
                              {l.status === "active" ? "Archive" : "Restore"}
                            </Button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryState>
      </Card>
      <Modal open={editing !== null} title={editing === "new" ? "Add location" : "Edit location"} onClose={() => setEditing(null)}>
        {editing !== null && <LocationForm location={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Modal>
    </>
  );
}

function LocationForm({ location, onDone }: { location: Location | null; onDone: () => void }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { name: location?.name ?? "", address: location?.address ?? "" },
  });
  async function onSubmit(values: z.infer<typeof schema>) {
    try {
      await api(location ? `/locations/${location.id}` : "/locations", { method: location ? "PATCH" : "POST", body: values });
      qc.invalidateQueries({ queryKey: ["locations"] });
      onDone();
    } catch (err) {
      setError(applyServerErrors(err, form.setError));
    }
  }
  return (
    <form className="form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
      {error && <Alert kind="error">{error}</Alert>}
      <TextInput label="Name" {...form.register("name")} error={form.formState.errors.name?.message} />
      <TextInput label="Address" {...form.register("address")} error={form.formState.errors.address?.message} />
      <div className="form-actions">
        <Button type="submit" variant="primary" loading={form.formState.isSubmitting}>
          Save location
        </Button>
      </div>
    </form>
  );
}
