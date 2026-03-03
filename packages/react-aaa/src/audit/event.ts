import { z } from 'zod';

export const EventTypeSchema = z.enum([
  'auth.login',
  'auth.logout',
  'auth.login_failed',
  'auth.token_refreshed',
  'auth.token_expired',
  'authz.access_granted',
  'authz.access_denied',
  'authz.permission_checked',
  'resource.created',
  'resource.read',
  'resource.updated',
  'resource.deleted',
  'admin.user_created',
  'admin.user_updated',
  'admin.user_deleted',
  'admin.role_assigned',
  'admin.role_revoked',
  'session.started',
  'session.ended',
]);

export const OutcomeSchema = z.enum(['success', 'failure', 'error']);

export const AuditEventSchema = z.object({
  type: EventTypeSchema,
  outcome: OutcomeSchema,
  actor: z.object({
    sub: z.string(),
    tenant: z.string().optional(),
  }),
  resource: z
    .object({
      type: z.string(),
      id: z.string().optional(),
    })
    .optional(),
  metadata: z.record(z.unknown()).optional(),
  timestamp: z.string().datetime().optional(),
  traceId: z.string().optional(),
});

export type EventType = z.infer<typeof EventTypeSchema>;
export type Outcome = z.infer<typeof OutcomeSchema>;
export type AuditEvent = z.infer<typeof AuditEventSchema>;
