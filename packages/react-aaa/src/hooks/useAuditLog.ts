import { useAuthContext } from '../components/AuthContext.js';
import type { AuditEvent } from '../audit/event.js';

export interface UseAuditLogReturn {
  emit: (event: AuditEvent) => void;
}

export function useAuditLog(): UseAuditLogReturn {
  const { emitter } = useAuthContext();

  function emit(event: AuditEvent): void {
    emitter?.emit(event);
  }

  return { emit };
}
