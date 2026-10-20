import { useEffect, useMemo, useState } from "react";
import { Check, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "../../core/api";

export function ProviderModelPicker({
  activeModel,
  configured,
  notify,
  onChanged,
}) {
  const [models, setModels] = useState([]);
  const [selected, setSelected] = useState(activeModel || "");
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => setSelected(activeModel || ""), [activeModel]);

  const loadModels = async () => {
    setLoading(true);
    try {
      const result = await api("/provider/models");
      setModels(result.items);
      setSelected(result.active || activeModel || result.items[0] || "");
    } catch (error) {
      notify("Could not load NVIDIA models", error.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (configured) loadModels();
  }, [configured]);

  const filteredModels = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return query
      ? models.filter((model) => model.toLowerCase().includes(query))
      : models;
  }, [filter, models]);

  const activate = async () => {
    if (!selected || selected === activeModel) return;
    setSaving(true);
    try {
      const result = await api("/provider/model", {
        method: "PUT",
        body: JSON.stringify({ model: selected }),
      });
      notify(
        "Active model changed",
        `${result.model} passed a live compatibility test.`,
      );
      await onChanged();
    } catch (error) {
      notify("Model switch failed", error.message);
    } finally {
      setSaving(false);
    }
  };

  if (!configured) return null;
  return (
    <section
      className="panel model-picker"
      aria-labelledby="model-picker-title"
    >
      <div className="model-picker-head">
        <div>
          <h2 id="model-picker-title">NVIDIA model selector</h2>
          <p>Choose from the models enabled for this NVIDIA account.</p>
        </div>
        <button
          type="button"
          onClick={loadModels}
          disabled={loading}
          title="Refresh models"
        >
          <RefreshCw className={loading ? "spin" : ""} size={16} />
        </button>
      </div>
      <label>
        Filter models
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Search Llama, Qwen, GPT OSS…"
        />
      </label>
      <label>
        Available model
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          {filteredModels.map((model) => (
            <option value={model} key={model}>
              {model}
            </option>
          ))}
        </select>
      </label>
      <div className="model-picker-actions">
        <span>
          <ShieldCheck size={14} /> {models.length} account models found
        </span>
        <button
          type="button"
          className="btn primary"
          disabled={saving || !selected || selected === activeModel}
          onClick={activate}
        >
          {saving ? (
            <Loader2 className="spin" size={14} />
          ) : (
            <Check size={14} />
          )}{" "}
          Activate & test
        </button>
      </div>
    </section>
  );
}
