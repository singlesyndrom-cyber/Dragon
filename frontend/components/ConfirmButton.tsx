"use client";

import { useEffect, useState } from "react";

/** Кнопка с подтверждением внутри страницы (без системного окна confirm, которое блокирует вкладку
 *  и плохо выглядит на телефоне). Первый клик показывает вопрос и кнопки «Да» / «Отмена». */
export default function ConfirmButton({ children, question, confirmLabel, onConfirm, disabled, className, danger }: {
  children: React.ReactNode; question: string; confirmLabel: string; onConfirm: () => void;
  disabled?: boolean; className?: string; danger?: boolean;   // danger - необратимое действие: красная кнопка «Да»
}) {
  const [asking, setAsking] = useState(false);
  useEffect(() => { if (disabled) setAsking(false); }, [disabled]);
  if (!asking) {
    return <button type="button" className={className} disabled={disabled} onClick={() => setAsking(true)}>{children}</button>;
  }
  return (
    <span className="confirm" role="group" aria-label={question}>
      <span className="confirm-q">{question}</span>
      <button type="button" className={danger ? "danger" : "primary"} autoFocus={!danger} onClick={() => { setAsking(false); onConfirm(); }}>{confirmLabel}</button>
      <button type="button" onClick={() => setAsking(false)}>Отмена</button>
    </span>
  );
}
