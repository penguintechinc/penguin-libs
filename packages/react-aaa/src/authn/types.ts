import { z } from 'zod';

export const ClaimsSchema = z.object({
  sub: z.string().max(256),
  iss: z.string(),
  aud: z.array(z.string()),
  iat: z.date(),
  exp: z.date(),
  scope: z.array(z.string()).optional(),
  roles: z.array(z.string()).optional(),
  teams: z.array(z.string()).optional(),
  tenant: z.string().optional(),
  ext: z.record(z.unknown()).optional(),
});

export const TokenSetSchema = z.object({
  access_token: z.string(),
  id_token: z.string().optional(),
  refresh_token: z.string().optional(),
  expires_in: z.number(),
  token_type: z.literal('Bearer'),
});

export type Claims = z.infer<typeof ClaimsSchema>;
export type TokenSet = z.infer<typeof TokenSetSchema>;
