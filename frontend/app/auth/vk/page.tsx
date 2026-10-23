"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { takePending } from "@/lib/vkid";

export default function VkReturnPage() {
  return <Suspense fallback={<p className="muted">Входим через VK…</p>}><VkReturn /></Suspense>;
}

/** Возврат с VK ID: код, state и device_id приходят параметрами (или JSON в payload). */
function VkReturn() {
  const p = useSearchParams();
  const router = useRouter();
  const { signIn } = useAuth();
  const [error, setError] = useState("");
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    let code = p.get("code"), state = p.get("state"), device = p.get("device_id");
    const payload = p.get("payload");
    if (payload) {
      try {
        const x = JSON.parse(payload);
        code = code || x.code; state = state || x.state; device = device || x.device_id;
      } catch {}
    }
    const pending = takePending();
    if (p.get("error")) { setError(`VK ID: ${p.get("error_description") || p.get("error")}`); return; }
    if (!code || !device || !pending || pending.state !== state) {
      setError("Не удалось проверить ответ VK ID: попробуйте ещё раз с той же вкладки.");
      return;
    }
    const body = { code, device_id: device, code_verifier: pending.verifier, state };
    (async () => {
      try {
        if (pending.purpose === "login") {
          const r = await api<any>("/auth/vk", { body });
          await signIn(r.access_token);
          router.replace(pending.back || "/me");
        } else if (pending.purpose === "link") {
          await api("/auth/vk/link", { body });
          router.replace("/me?vk=linked");
        } else {
          await api(`/clubs/${pending.clubId}/vk/wall/vkid`, { body });
          router.replace(`/manage/clubs/${pending.clubId}/vk?wall=connected`);
        }
      } catch (e: any) {
        setError(e.message || "VK ID не подтвердил вход");
      }
    })();
  }, [p, router, signIn]);

  return (
    <>
      <h1>VK</h1>
      {error ? (
        <>
          <p className="err">{error}</p>
          <p><Link href="/login">Ко входу</Link> · <Link href="/me">В кабинет</Link></p>
        </>
      ) : <p className="muted">Проверяем вход через VK…</p>}
    </>
  );
}
