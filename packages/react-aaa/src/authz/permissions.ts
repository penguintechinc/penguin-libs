export function hasScope(scopes: string[], required: string): boolean {
  return scopes.includes(required);
}

export function hasAnyScope(scopes: string[], required: string[]): boolean {
  return required.some((scope) => scopes.includes(scope));
}

export function hasAllScopes(scopes: string[], required: string[]): boolean {
  return required.every((scope) => scopes.includes(scope));
}

export function hasRole(roles: string[], required: string): boolean {
  return roles.includes(required);
}
