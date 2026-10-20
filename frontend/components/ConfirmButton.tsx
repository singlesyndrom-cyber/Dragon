"use client";

import { useEffect, useState } from "react";

/** Кнопка с подтверждением внутри страницы (без системного окна confirm, которое блокирует вкладку
 *  и плохо выглядит на телефоне). Первый клик показывает вопрос и кнопки «Да» / «Отмена». */
export default function ConfirmButton({ children, question, confirmLabel, onConfirm, disabled, className }: {
  children: React.ReactNode; question: string; confirmLabel: string; onConfirm: () => void;
  disabled?: boolean; className?: string;
}) {
  const [asking, setAsking] = useState(false);
  useEffect(() => { if (disabled) setAsking(false); }, [disabled]);
  if (!asking) {
    return <button type="button" className={className} disabled={disabled} onClick={() => setAsking(true)}>{children}</button>;
  }
  return (
    <span className="confirm" role="group" aria-label={question}>
      <span className="confirm-q">{question}</span>
      <button type="button" className="primary" autoFocus onClick={() => { setAsking(false); onConfirm(); }}>{confirmLabel}</button>
      <button type="button" onClick={() => setAsking(false)}>Отмена</button>
    </span>
  );
}
