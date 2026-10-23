"use client";

import { useEffect, useState } from "react";
import { VkPurpose, startVk, vkConfig } from "@/lib/vkid";

/** Кнопка VK ID. Пока на сервере не задан VK_APP_ID - не показывается. */
export default function VkButton({ purpose, label, clubId, scope, back }: {
  purpose: VkPurpose; label: string; clubId?: number; scope?: string; back?: string;
}) {
  const [enabled, setEnabled] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { vkConfig().then((c) => setEnabled(c.enabled)); }, []);
  if (!enabled) return null;
  return (
    <span className="stack">
      <button type="button" className="vkbtn" onClick={() => startVk(purpose, { clubId, scope, back }).catch((e) => setErr(e.message))}>
        {label}
      </button>
      {err ? <span className="err small">{err}</span> : null}
    </span>
  );
}
