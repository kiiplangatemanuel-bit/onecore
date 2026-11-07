# Core authorization

Organization membership roles are enforced server-side through
`app.core.authorization`. Unknown roles deny all actions by default.

| Role | Read | Create | Update | Delete | Manage |
|---|---:|---:|---:|---:|---:|
| org_admin | yes | yes | yes | yes | yes |
| branch_admin | yes | yes | yes | yes | no |
| manager | yes | yes | yes | no | no |
| accountant | yes | yes | yes | no | no |
| staff | yes | yes | no | no | no |
| viewer | yes | no | no | no | no |

`Membership.branch_scope` uses `*` for all branches or a comma-separated
allow-list. Empty scope grants no branch access. Branch filtering is applied
in the records query, not in the frontend. Record updates and deletes verify
both organization and module ownership before mutation.

This is a foundational generic-record policy, not a complete product-specific
permission matrix. Each domain must add its own finer-grained permissions and
negative authorization tests before release.
