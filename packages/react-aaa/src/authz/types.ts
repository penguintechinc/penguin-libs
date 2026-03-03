import { z } from 'zod';

export const RoleSchema = z.object({
  name: z.string(),
  scopes: z.array(z.string()),
});

export const RBACConfigSchema = z.object({
  roles: z.array(RoleSchema),
});

export type Role = z.infer<typeof RoleSchema>;
export type RBACConfig = z.infer<typeof RBACConfigSchema>;
