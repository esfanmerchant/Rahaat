import type { paths } from './schema';

/**
 * App-facing API types, derived from `paths` only, so they survive
 * `npm run gen:api` even if the backend names its schemas differently.
 * Add a line here for each new endpoint you use.
 */
type Json<T> = T extends { content: { 'application/json': infer Body } } ? Body : never;

export type AuthOut = Json<paths['/v1/auth/login']['post']['responses'][200]>;
export type LoginBody = Json<paths['/v1/auth/login']['post']['requestBody']>;
export type SwitchBody = Json<paths['/v1/auth/switch']['post']['requestBody']>;
export type MeOut = Json<paths['/v1/auth/me']['get']['responses'][200]>;
export type SystemInfo = Json<paths['/v1/system/info']['get']['responses'][200]>;
export type DemoAccountsOut = Json<paths['/v1/demo/accounts']['get']['responses'][200]>;
export type DemoAccount = DemoAccountsOut['accounts'][number];

export type AuthUser = AuthOut['user'];
export type ActiveMembership = AuthOut['active'];
export type Membership = AuthOut['memberships'][number];
export type Role = ActiveMembership['role'];
