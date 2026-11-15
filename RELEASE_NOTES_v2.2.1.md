# OpenVPN Wizard v2.2.1 — preflight safety hotfix

Before any package, firewall, HAProxy, or OpenVPN change, the wizard now runs
a read-only safety preflight. It refuses foreign port owners and incompatible
HAProxy frontends without changing the server.
