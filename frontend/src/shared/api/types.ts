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

// Spine API used by the citizen app (docs/CONTRACTS.md).
export type PersonOut = Json<paths['/v1/me/person']['get']['responses'][200]>;
export type ProgramOut = Json<paths['/v1/programs']['get']['responses'][200]>[number];
export type ConsentOut = Json<paths['/v1/consents']['post']['responses'][201]>;
export type ConsentCreate = Json<paths['/v1/consents']['post']['requestBody']>;
export type ApplicationList = Json<paths['/v1/applications']['get']['responses'][200]>;
export type ApplicationSummary = ApplicationList['items'][number];
export type ApplicationOut = Json<paths['/v1/applications/{application_id}']['get']['responses'][200]>;
export type ApplicationStatus = ApplicationOut['status'];
export type ApplicationForm = ApplicationOut['form'];
export type DocumentOut = Json<paths['/v1/applications/{application_id}/documents']['post']['responses'][201]>;
export type DocumentView = DocumentOut['document'];
export type DocumentKind = DocumentView['kind'];
export type SubmitOut = Json<paths['/v1/applications/{application_id}/submit']['post']['responses'][200]>;
export type DecisionUserView = NonNullable<SubmitOut['decision']>;
export type DecisionOutcome = DecisionUserView['outcome'];
export type Explanation = DecisionUserView['explanation'];
export type TimelineItem = NonNullable<ApplicationOut['timeline']>[number];
export type IncomeBand = NonNullable<NonNullable<ApplicationForm['income_band']>['value']>;
