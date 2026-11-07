# Master specification addendum — domain and global attribution

Source: OneCore Complete Ecosystem & Workflow Master Specification, addendum pages 22–25.

## Organization custom domains
- Provide tenant-admin domain management for eligible subscriptions.
- Support apex/subdomains where infrastructure permits.
- Display DNS records and setup instructions; verify ownership before activation.
- Prevent one verified domain from being assigned to unrelated tenants.
- Support primary/additional domains, redirects, diagnostics and lifecycle states:
  Not Connected, Pending DNS, Verification Required, Provisioning, Active, SSL Error, Expired, Suspended.
- Provision/renew TLS where supported; monitor certificate health.
- Enforce host-to-tenant mapping at edge and application layers; reject unknown hosts.
- Audit domain, verification, certificate, redirect and administrative events.

## Mandatory global OneCore attribution
Exact footer text: **Powered by OneCore Technologies Ltd**
- Render in every customer-facing OneCore page footer, including tenant custom domains.
- Link to the configured canonical corporate URL.
- Implement centrally; tenant admins and page builders cannot hide or obscure it.
- Ensure responsive/accessibility compatibility and test all themes/routes/modules.
- Any exception requires separate OneCore company-level authorization.

## Important
These are target requirements, not evidence of completed implementation. Add the feature to the definition-of-done and release process before production claims.
